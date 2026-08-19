import datetime as dt

import pytest
from pydantic import ValidationError

from sigma.domain import CorporateAction, EventDetail, EventType, Exchange
from tests.fakes import fake_action


def test_the_exchange_knows_its_yfinance_suffix():
    assert Exchange.NSE.suffix == ".NS"
    assert Exchange.BSE.suffix == ".BO"


def test_a_ticker_from_the_wrong_exchange_is_rejected():
    # The bug this catches is silent: mapping BSE's short_name to JOJO.BO
    # resolves to nothing at Yahoo and produces an empty result, not an error.
    with pytest.raises(ValidationError, match="not a BSE ticker"):
        fake_action(Exchange.BSE, "531910", ticker="JOJO.NS")


def test_the_bse_symbol_is_the_scrip_code():
    action = fake_action(Exchange.BSE, "531910")
    assert action.ticker == "531910.BO"


def test_an_nse_symbol_with_an_ampersand_survives():
    # GVT&D is a real NSE symbol. Day 07's Symbol pattern rejected it, which
    # would have dropped one company out of a market-wide feed with no error.
    assert fake_action(Exchange.NSE, "GVT&D").ticker == "GVT&D.NS"


def test_the_key_is_exchange_scoped_on_purpose():
    # Kirloskar Pneumatic, same 2-for-1 split, same ex-date, two exchanges.
    bse = fake_action(Exchange.BSE, "505283", ex_date=dt.date(2026, 8, 18))
    nse = fake_action(Exchange.NSE, "KIRLPNU", ex_date=dt.date(2026, 8, 18))
    assert bse.key != nse.key


def test_two_dividends_in_one_window_are_two_events():
    first = fake_action(ex_date=dt.date(2026, 8, 20))
    second = fake_action(ex_date=dt.date(2026, 9, 20))
    assert first.key != second.key


def test_the_event_type_comes_from_the_detail():
    action = fake_action(detail=EventDetail(type=EventType.BUYBACK))
    assert action.event_type is EventType.BUYBACK


def test_a_ratio_needs_both_halves():
    with pytest.raises(ValidationError, match="both halves"):
        EventDetail(type=EventType.BONUS, ratio_new=2)


def test_a_face_value_change_must_shrink():
    with pytest.raises(ValidationError, match="not a sub-division"):
        EventDetail(type=EventType.SPLIT, face_value_from=1, face_value_to=10)


def test_a_zero_dividend_is_not_a_dividend():
    with pytest.raises(ValidationError, match="not positive"):
        EventDetail(type=EventType.DIVIDEND, amount=0)


def test_the_raw_text_is_required_and_survives():
    action = fake_action(raw="Resolution Plan -Suspension")
    assert action.raw == "Resolution Plan -Suspension"
    with pytest.raises(ValidationError):
        CorporateAction.model_validate(
            {
                "exchange": Exchange.NSE,
                "symbol": "X",
                "ticker": "X.NS",
                "detail": EventDetail(type=EventType.UNKNOWN),
                "ex_date": dt.date(2026, 8, 20),
            }
        )


def test_a_model_can_read_back_what_it_wrote():
    # extra='forbid' plus a computed field used to make this impossible: the
    # dump carried split_factor and validation refused it. Day 12 caches these.
    action = fake_action(
        detail=EventDetail(type=EventType.SPLIT, face_value_from=10, face_value_to=1)
    )
    assert CorporateAction.model_validate_json(action.model_dump_json()) == action
