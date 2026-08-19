"""Yahoo's vocabulary, translated once.

Every yfinance spelling in the project lives in this file and in `provider.py`
beside it. Nothing here does I/O, so the whole translation is testable against
a literal dict.
"""

import math
from collections.abc import Mapping
from typing import Any, cast

import pandas as pd
from pydantic import ValidationError

from sigma.domain import CompanyProfile, PriceBar, Quote, TickerSnapshot
from sigma.logging import get_logger

logger = get_logger(__name__)

# Our name -> the Yahoo names that can carry it, in order of preference.
# Indices and BSE scrips have no 'currentPrice' at all: ^GSPC and 531910.BO
# both return None there and a real price under 'regularMarketPrice'.
QUOTE_KEYS: dict[str, tuple[str, ...]] = {
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

PROFILE_KEYS: dict[str, tuple[str, ...]] = {
    # longName only. Yahoo's shortName for a BSE scrip is a machine identifier -
    # 531910.BO returns '531910.BO,0P0000BRKR,244' - and junk that parses as a
    # name is worse than no name, because `or symbol` renders no name correctly.
    "name": ("longName",),
    "sector": ("sector",),
    "industry": ("industry",),
}


def present(info: Mapping[str, Any], keys: tuple[str, ...]) -> Any | None:
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


def to_bars(history: pd.DataFrame | None, symbol: str) -> tuple[PriceBar, ...]:
    """DataFrame -> domain. This function is where numpy scalars stop existing."""
    if history is None or history.empty:
        return ()

    bars: list[PriceBar] = []
    rejected = 0
    for timestamp, row in history.iterrows():
        # iterrows() only promises Hashable for the index; yfinance always returns a
        # DatetimeIndex. This cast is the pandas escape hatch, and it lives here
        # because this is the only package allowed to touch a DataFrame.
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
        logger.warning("bars_rejected", symbol=symbol, rejected=rejected, kept=len(bars))
    return tuple(bars)


def to_snapshot(
    symbol: str, info: Mapping[str, Any], history: pd.DataFrame | None
) -> TickerSnapshot:
    # model_validate, not the constructor: this data came off the wire, so its
    # types are a claim rather than a fact. The constructor is for values we
    # already know the type of; validation is for values we do not.
    profile = CompanyProfile.model_validate(
        {"symbol": symbol} | {f: present(info, keys) for f, keys in PROFILE_KEYS.items()}
    )
    quote = Quote.model_validate(
        {"symbol": symbol} | {f: present(info, keys) for f, keys in QUOTE_KEYS.items()}
    )
    return TickerSnapshot(profile=profile, quote=quote, bars=to_bars(history, symbol))
