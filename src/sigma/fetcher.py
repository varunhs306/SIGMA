import asyncio
import math
from collections.abc import Mapping
from typing import Any, cast

import pandas as pd
import yfinance as yf
from pydantic import TypeAdapter, ValidationError

from sigma.config import get_settings
from sigma.domain import CompanyProfile, PriceBar, Quote, Symbol, TickerSnapshot
from sigma.exceptions import ProviderError, ProviderRateLimited, SymbolNotFoundError
from sigma.logging import get_logger

logger = get_logger(__name__)

FetchError = ProviderError
InvalidTickerError = SymbolNotFoundError
RateLimitError = ProviderRateLimited

_SYMBOL = TypeAdapter(Symbol)

# Our name -> the Yahoo names that can carry it, in order of preference.
# Indices and BSE scrips have no 'currentPrice' at all: ^GSPC and 531910.BO
# both return None there and a real price under 'regularMarketPrice'.
_QUOTE_KEYS: dict[str, tuple[str, ...]] = {
    "price": ("currentPrice", "regularMarketPrice"),
    "market_cap": ("marketCap",),
    "trailing_pe": ("trailingPE",),
    "forward_pe": ("forwardPE",),
    "price_to_book": ("priceToBook",),
    "week_52_high": ("fiftyTwoWeekHigh",),
    "week_52_low": ("fiftyTwoWeekLow",),
    "volume": ("volume", "regularMarketVolume"),
    "avg_volume": ("averageVolume",),
    "beta": ("beta",),
    "dividend_yield": ("dividendYield",),
}

_PROFILE_KEYS: dict[str, tuple[str, ...]] = {
    # longName only. Yahoo's shortName for a BSE scrip is a machine identifier -
    # 531910.BO returns '531910.BO,0P0000BRKR,244' - and junk that parses as a
    # name is worse than no name, because `or symbol` renders no name correctly.
    "name": ("longName",),
    "sector": ("sector",),
    "industry": ("industry",),
}


async def _fetch_from_yfinance(symbol: str) -> tuple[dict[str, Any], pd.DataFrame]:
    loop = asyncio.get_event_loop()

    def blocking_fetch() -> tuple[dict[str, Any], pd.DataFrame]:
        tz_cache = get_settings().data_dir / "yf-tz-cache"
        tz_cache.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(tz_cache))
        ticker = yf.Ticker(symbol)
        info = ticker.info
        history = ticker.history(period=get_settings().history_period)
        return info, history

    return await loop.run_in_executor(None, blocking_fetch)


def _present(info: Mapping[str, Any], keys: tuple[str, ...]) -> Any | None:
    """Yahoo spells absence four ways. The domain spells it one way: None.

    Missing key, explicit None, a pandas nan, and the empty string all mean the
    same thing upstream, and translating vendor vocabulary is this layer's job.
    """
    for key in keys:
        value = info.get(key)
        if value is None:
            continue
        if isinstance(value, float) and not math.isfinite(value):
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _to_bars(history: pd.DataFrame | None, log: Any) -> tuple[PriceBar, ...]:
    """DataFrame -> domain. This function is where numpy scalars stop existing."""
    if history is None or history.empty:
        return ()

    bars: list[PriceBar] = []
    rejected = 0
    for timestamp, row in history.iterrows():
        # iterrows() only promises Hashable for the index; yfinance always returns a
        # DatetimeIndex. This cast is the pandas escape hatch, and it lives here
        # because this is the only module allowed to touch a DataFrame.
        ts = cast(pd.Timestamp, timestamp)
        try:
            bars.append(
                PriceBar(
                    date=ts.date(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                )
            )
        except (ValidationError, ValueError, TypeError):
            # One unusable row must not cost the other 21. Dropped loudly, per Day 04.
            rejected += 1

    if rejected:
        log.warning("bars_rejected", rejected=rejected, kept=len(bars))
    return tuple(bars)


def _to_snapshot(
    symbol: str, info: Mapping[str, Any], history: pd.DataFrame | None, log: Any
) -> TickerSnapshot:
    # model_validate, not the constructor: this data came off the wire, so its
    # types are a claim rather than a fact. The constructor is for values we
    # already know the type of; validation is for values we do not.
    profile = CompanyProfile.model_validate(
        {"symbol": symbol} | {f: _present(info, keys) for f, keys in _PROFILE_KEYS.items()}
    )
    quote = Quote.model_validate(
        {"symbol": symbol} | {f: _present(info, keys) for f, keys in _QUOTE_KEYS.items()}
    )
    return TickerSnapshot(profile=profile, quote=quote, bars=_to_bars(history, log))


async def fetch_ticker(symbol: str) -> TickerSnapshot:
    log = logger.bind(ticker=symbol)

    try:
        symbol = _SYMBOL.validate_python(symbol)
    except ValidationError as e:
        log.warning("invalid_ticker_format")
        raise InvalidTickerError(f"'{symbol}' is not a valid ticker format") from e

    try:
        info, history = await _fetch_from_yfinance(symbol)
    except Exception as e:
        # HACK(day-08): classifying by exception message text. yfinance raises bare
        # Exception for everything, so there is nothing else to switch on until it is
        # behind an adapter with its own error taxonomy.
        error_str = str(e).lower()
        if "429" in error_str or "too many requests" in error_str:
            log.warning("rate_limited")
            raise RateLimitError("Yahoo rate limit hit") from e
        log.error("yfinance_fetch_failed", error=str(e))
        raise FetchError(f"Failed to fetch data for {symbol}") from e

    log.info("yfinance_fetch_success", info_fields=len(info), history_rows=len(history))

    try:
        snapshot = _to_snapshot(symbol, info, history, log)
    except ValidationError as e:
        # No price is how a delisted or misspelled symbol arrives: Quote.price is
        # required, so the old _is_valid_ticker_response check is now the type.
        if any(err["loc"] == ("price",) for err in e.errors()):
            log.warning("invalid_ticker_no_price_data", fields_returned=len(info))
            raise InvalidTickerError(
                f"'{symbol}' returned no price data - may be invalid or delisted"
            ) from e
        log.error("provider_payload_rejected", error_count=e.error_count(), errors=e.errors())
        raise FetchError(f"'{symbol}' returned data that failed validation") from e

    log.info("fetch_complete", bars=len(snapshot.bars))
    return snapshot
