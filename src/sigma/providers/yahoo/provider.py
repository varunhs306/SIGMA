"""The Yahoo adapter. The only module in the project that calls yfinance."""

import asyncio
from typing import Any

import pandas as pd
import yfinance as yf
from pydantic import TypeAdapter, ValidationError

from sigma.config import get_settings
from sigma.domain import Symbol, TickerSnapshot
from sigma.exceptions import ProviderError, ProviderRateLimited, SymbolNotFoundError
from sigma.logging import get_logger
from sigma.providers.yahoo.mapper import to_snapshot

logger = get_logger(__name__)

_SYMBOL = TypeAdapter(Symbol)


class YahooProvider:
    """Satisfies `MarketDataProvider`, and says so nowhere.

    Structural subtyping: there is no base class to inherit and no registration
    step. `tests/test_provider_protocol.py` is what asserts the shape holds.
    """

    name = "yahoo"

    async def _fetch(self, symbol: str) -> tuple[dict[str, Any], pd.DataFrame]:
        loop = asyncio.get_event_loop()

        def blocking_fetch() -> tuple[dict[str, Any], pd.DataFrame]:
            tz_cache = get_settings().data_dir / "yf-tz-cache"
            tz_cache.mkdir(parents=True, exist_ok=True)
            yf.set_tz_cache_location(str(tz_cache))
            ticker = yf.Ticker(symbol)
            info = ticker.info
            history = ticker.history(period=get_settings().history_period)
            return info, history

        # TODO(day-10): no timeout. TODO(day-11): replaces this with asyncio.to_thread
        # under a bounded semaphore.
        return await loop.run_in_executor(None, blocking_fetch)

    async def get_snapshot(self, symbol: str) -> TickerSnapshot:
        log = logger.bind(ticker=symbol, provider=self.name)

        try:
            symbol = _SYMBOL.validate_python(symbol)
        except ValidationError as e:
            log.warning("invalid_ticker_format")
            raise SymbolNotFoundError(f"'{symbol}' is not a valid ticker format") from e

        try:
            info, history = await self._fetch(symbol)
        except Exception as e:
            # Still classifying by exception message text, because yfinance raises
            # bare Exception for everything. What changed today is the blast radius:
            # this string matching is now confined to one class in one package.
            error_str = str(e).lower()
            if "429" in error_str or "too many requests" in error_str:
                log.warning("rate_limited")
                raise ProviderRateLimited("Yahoo rate limit hit") from e
            log.error("yfinance_fetch_failed", error=str(e))
            raise ProviderError(f"Failed to fetch data for {symbol}") from e

        log.info("yfinance_fetch_success", info_fields=len(info), history_rows=len(history))

        try:
            snapshot = to_snapshot(symbol, info, history)
        except ValidationError as e:
            # No price is how a delisted or misspelled symbol arrives: Quote.price is
            # required, so the old _is_valid_ticker_response check is now the type.
            if any(err["loc"] == ("price",) for err in e.errors()):
                log.warning("invalid_ticker_no_price_data", fields_returned=len(info))
                raise SymbolNotFoundError(
                    f"'{symbol}' returned no price data - may be invalid or delisted"
                ) from e
            log.error("provider_payload_rejected", error_count=e.error_count(), errors=e.errors())
            raise ProviderError(f"'{symbol}' returned data that failed validation") from e

        log.info("fetch_complete", bars=len(snapshot.bars))
        return snapshot
