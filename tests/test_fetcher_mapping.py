import math

import pandas as pd
import pytest

from sigma.exceptions import ProviderError, SymbolNotFoundError
from sigma.fetcher import _present, _to_bars, _to_snapshot, fetch_ticker
from sigma.logging import get_logger

log = get_logger("test")

# ^GSPC and 531910.BO both look like this: no currentPrice, a real price one key over.
INDEX_INFO = {"regularMarketPrice": 7691.76, "longName": "S&P 500"}


def _frame(rows):
    return pd.DataFrame(
        rows, index=pd.to_datetime([f"2026-07-{i + 1:02d}" for i in range(len(rows))])
    )


def test_the_price_falls_back_to_the_next_key():
    snapshot = _to_snapshot("^GSPC", INDEX_INFO, None, log)
    assert snapshot.quote.price == 7691.76
    assert snapshot.profile.name == "S&P 500"


def test_yahoos_four_spellings_of_absence_all_become_none():
    info = {"sector": "", "beta": float("nan"), "marketCap": None}
    assert _present(info, ("sector",)) is None
    assert _present(info, ("beta",)) is None
    assert _present(info, ("marketCap",)) is None
    assert _present(info, ("industry",)) is None  # key not there at all


async def test_no_price_under_any_key_is_a_symbol_error(monkeypatch):
    async def no_price(symbol):
        return {"longName": "Delisted Inc"}, _frame([])

    monkeypatch.setattr("sigma.fetcher._fetch_from_yfinance", no_price)
    # Quote.price being required is what makes this a SymbolNotFoundError. The
    # old _is_valid_ticker_response function is now a field declaration.
    with pytest.raises(SymbolNotFoundError):
        await fetch_ticker("DEAD")


async def test_a_payload_that_fails_validation_is_a_provider_error(monkeypatch):
    async def impossible(symbol):
        return {"currentPrice": 100.0, "fiftyTwoWeekHigh": 90.0, "fiftyTwoWeekLow": 110.0}, _frame(
            []
        )

    monkeypatch.setattr("sigma.fetcher._fetch_from_yfinance", impossible)
    with pytest.raises(ProviderError) as exc:
        await fetch_ticker("AAPL")
    assert not isinstance(exc.value, SymbolNotFoundError)


async def test_a_malformed_symbol_never_reaches_the_network(monkeypatch):
    async def explode(symbol):
        raise AssertionError("the network was called")

    monkeypatch.setattr("sigma.fetcher._fetch_from_yfinance", explode)
    with pytest.raises(SymbolNotFoundError):
        await fetch_ticker("<script>")


def test_bars_carry_python_floats_not_numpy_scalars():
    bars = _to_bars(
        _frame([{"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10}]), log
    )
    assert type(bars[0].close) is float


def test_one_unusable_row_does_not_cost_the_others():
    frame = _frame(
        [
            {"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10},
            {"Open": math.nan, "High": math.nan, "Low": math.nan, "Close": math.nan, "Volume": 0},
            {"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.8, "Volume": 11},
        ]
    )
    bars = _to_bars(frame, log)
    assert len(bars) == 2
    assert [bar.close for bar in bars] == [1.5, 1.8]


def test_an_empty_history_is_no_bars_not_a_zero_change():
    snapshot = _to_snapshot("^GSPC", INDEX_INFO, _frame([]), log)
    assert snapshot.bars == ()
    assert snapshot.price_change_30d is None
