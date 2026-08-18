import datetime as dt

import pytest
from pydantic import TypeAdapter, ValidationError

from sigma.domain import CompanyProfile, PriceBar, Quote, Symbol, TickerSnapshot
from tests.fakes import fake_bars, fake_snapshot

symbol_of = TypeAdapter(Symbol).validate_python


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("aapl", "AAPL"),
        (" AAPL ", "AAPL"),
        ("brk-b", "BRK-B"),
        ("^gspc", "^GSPC"),
        ("reliance.ns", "RELIANCE.NS"),  # 11 chars: the old 10-char regex rejected it
        ("tatamotors.ns", "TATAMOTORS.NS"),  # 13
        ("531910.bo", "531910.BO"),
    ],
)
def test_symbols_are_normalised_not_rejected(raw, expected):
    assert symbol_of(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "AAPL AAPL", "AAPL;DROP", "A" * 21, "APPL$"])
def test_symbols_that_are_not_symbols_are_rejected(raw):
    with pytest.raises(ValidationError):
        symbol_of(raw)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0])
def test_a_price_is_a_positive_finite_number(bad):
    # nan and inf are the ones people forget: pydantic allows both by default,
    # and pandas produces both. See §1.3.
    with pytest.raises(ValidationError):
        Quote(symbol="AAPL", price=bad)


def test_a_quote_without_a_price_cannot_be_built():
    with pytest.raises(ValidationError) as exc:
        Quote(symbol="AAPL")
    assert exc.value.errors()[0]["loc"] == ("price",)


def test_optional_metrics_stay_absent_rather_than_becoming_zero():
    quote = Quote(symbol="AAPL", price=100.0)
    assert quote.trailing_pe is None
    assert quote.market_cap is None


def test_a_typo_in_a_field_name_is_an_error_not_a_shrug():
    with pytest.raises(ValidationError) as exc:
        Quote(symbol="AAPL", price=100.0, trailng_pe=30.0)
    assert exc.value.errors()[0]["type"] == "extra_forbidden"


def test_models_are_frozen():
    quote = Quote(symbol="AAPL", price=100.0)
    with pytest.raises(ValidationError):
        quote.price = 200.0


def test_an_inverted_52_week_range_is_rejected():
    with pytest.raises(ValidationError, match="52-week high"):
        Quote(symbol="AAPL", price=100.0, week_52_high=90.0, week_52_low=110.0)


def test_a_bar_whose_close_is_outside_its_range_is_rejected():
    with pytest.raises(ValidationError, match="close"):
        PriceBar(date=dt.date(2026, 7, 1), open=10, high=11, low=9, close=99, volume=1)


def test_price_change_is_none_below_two_bars():
    # One bar is not a change. Reporting 0.00% for it is the §1.4 defect.
    assert fake_snapshot(closes=(100.0,)).price_change_30d is None
    assert fake_snapshot(closes=()).price_change_30d is None


def test_price_change_is_computed_from_the_first_and_last_bar():
    assert fake_snapshot(closes=(100.0, 50.0, 110.0)).price_change_30d == 10.0
    assert fake_snapshot(closes=(100.0, 90.0)).price_change_30d == -10.0


def test_a_flat_run_is_zero_and_zero_is_not_absence():
    snapshot = fake_snapshot(closes=(100.0, 100.0))
    assert snapshot.price_change_30d == 0.0
    assert snapshot.price_change_30d is not None


def test_bars_out_of_order_are_rejected():
    ordered = fake_bars((100.0, 101.0, 102.0))
    with pytest.raises(ValidationError, match="chronological"):
        TickerSnapshot(
            profile=CompanyProfile(symbol="AAPL"),
            quote=Quote(symbol="AAPL", price=102.0),
            bars=tuple(reversed(ordered)),
        )


def test_a_snapshot_cannot_mix_two_companies():
    with pytest.raises(ValidationError, match="profile is"):
        TickerSnapshot(
            profile=CompanyProfile(symbol="AAPL"),
            quote=Quote(symbol="MSFT", price=100.0),
        )


def test_the_computed_field_is_part_of_the_serialised_form():
    # It has to be: Day 12 caches this object, and a cached snapshot that loses
    # its derived values is a different object on the way back out.
    dumped = fake_snapshot(closes=(100.0, 110.0)).model_dump()
    assert dumped["price_change_30d"] == 10.0
