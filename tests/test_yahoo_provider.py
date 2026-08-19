import pandas as pd
import pytest

from sigma.exceptions import ProviderError, ProviderRateLimited, SymbolNotFoundError
from sigma.providers.yahoo import YahooProvider


def _frame(rows):
    return pd.DataFrame(
        rows, index=pd.to_datetime([f"2026-07-{i + 1:02d}" for i in range(len(rows))])
    )


def _provider_returning(info, history=None):
    """A YahooProvider with its one network method replaced.

    Subclassing beats monkeypatching a module attribute here: the seam is the
    method, and overriding it cannot leak into another test.
    """

    class Stubbed(YahooProvider):
        async def _fetch(self, symbol):
            return info, _frame([]) if history is None else history

    return Stubbed()


def _provider_raising(error):
    class Exploding(YahooProvider):
        async def _fetch(self, symbol):
            raise error

    return Exploding()


async def test_no_price_under_any_key_is_a_symbol_error():
    # Quote.price being required is what makes this a SymbolNotFoundError. The
    # old _is_valid_ticker_response function is now a field declaration.
    with pytest.raises(SymbolNotFoundError):
        await _provider_returning({"longName": "Delisted Inc"}).get_snapshot("DEAD")


async def test_a_payload_that_fails_validation_is_a_provider_error():
    impossible = {"currentPrice": 100.0, "fiftyTwoWeekHigh": 90.0, "fiftyTwoWeekLow": 110.0}
    with pytest.raises(ProviderError) as exc:
        await _provider_returning(impossible).get_snapshot("AAPL")
    assert not isinstance(exc.value, SymbolNotFoundError)


async def test_a_malformed_symbol_never_reaches_the_network():
    class Tripwire(YahooProvider):
        async def _fetch(self, symbol):
            raise AssertionError("the network was called")

    with pytest.raises(SymbolNotFoundError):
        await Tripwire().get_snapshot("<script>")


async def test_a_429_in_the_message_becomes_a_rate_limit_error():
    # yfinance raises bare Exception for everything, so the status code is only
    # available as text. This is the whole reason that hack is confined here.
    with pytest.raises(ProviderRateLimited):
        await _provider_raising(Exception("429 Too Many Requests")).get_snapshot("AAPL")


async def test_any_other_upstream_failure_becomes_a_provider_error():
    with pytest.raises(ProviderError) as exc:
        await _provider_raising(Exception("connection reset")).get_snapshot("AAPL")
    assert not isinstance(exc.value, ProviderRateLimited)


async def test_a_good_payload_becomes_a_snapshot():
    bars = _frame(
        [
            {"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.0, "Volume": 10},
            {"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.1, "Volume": 11},
        ]
    )
    snapshot = await _provider_returning({"currentPrice": 1.1}, bars).get_snapshot("aapl")
    # Lower case in, canonical symbol out: normalisation is the domain's job.
    assert snapshot.symbol == "AAPL"
    assert snapshot.price_change_30d == 10.0
