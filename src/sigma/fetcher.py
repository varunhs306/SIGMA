import asyncio
import re
import time
from typing import Optional

import yfinance as yf
from sigma.logging import get_logger
from sigma.config import get_settings
from sigma.exceptions import ProviderError, ProviderRateLimited, SymbolNotFoundError
logger = get_logger(__name__)

FetchError = ProviderError
InvalidTickerError = SymbolNotFoundError
RateLimitError = ProviderRateLimited

def _validate_symbol(symbol: str) -> bool:
    return bool(re.match(r'^[A-Z0-9.\-\^]{1,10}$', symbol.upper()))

async def _fetch_from_yfinance(symbol: str) -> tuple:
    loop = asyncio.get_event_loop()

    def blocking_fetch():
        ticker = yf.Ticker(symbol)
        info = ticker.info
        history = ticker.history(period=get_settings().history_period)
        return info,history
    
    return await loop.run_in_executor(None,blocking_fetch)

def _get_optional(data: dict, key: str, log, default=None):
    value = data.get(key, default)
    if value is None:
        log.debug("field_absent", field=key)
        return default
    return value

def _build_clean_data(symbol: str, info: dict, history, log) -> dict:
    # None, not 0: "we have no history" must not render as "the stock did not move".
    price_change_30d = None

    if history is not None and not history.empty:
        first_close = history['Close'].iloc[0]
        last_close = history['Close'].iloc[-1]
        price_change_30d = round(((last_close - first_close) / first_close) * 100, 2)

    return {
        "symbol":symbol,
        "company_name":_get_optional(info,"longName",log),
        "current_price":_get_optional(info,"currentPrice",log),
        "market_cap":_get_optional(info,"marketCap",log),
        "trailing_pe":_get_optional(info,"trailingPE",log),
        "forward_pe":_get_optional(info,"forwardPE",log),
        "price_to_book":_get_optional(info,"priceToBook",log),
        "week_52_high":_get_optional(info,"fiftyTwoWeekHigh",log),
        "week_52_low":_get_optional(info,"fiftyTwoWeekLow",log),
        "volume":_get_optional(info,"volume",log),
        "avg_volume":_get_optional(info,"averageVolume",log),
        "beta":_get_optional(info,"beta",log),
        "dividend_yield":_get_optional(info,"dividendYield",log),
        "sector":_get_optional(info,"sector",log),
        "industry":_get_optional(info,"industry",log),
        "price_change_30d":price_change_30d,
    }

def _is_valid_ticker_response(info):
    has_price = (info.get("currentPrice") != None or info.get("regularMarketPrice") != None)
    return has_price

async def fetch_ticker(symbol: str) -> dict:
    log = logger.bind(ticker=symbol)

    if not _validate_symbol(symbol):
        log.warning("invalid_ticker_format")
        raise InvalidTickerError(f"'{symbol}' is not a valid Ticker format")
    
    try:
        info, history = await _fetch_from_yfinance(symbol)
    except Exception as e:
        # HACK(day-08): classifying by exception message text. yfinance raises bare
        # Exception for everything, so there is nothing else to switch on until it is
        # behind an adapter with its own error taxonomy.
        error_str = str(e).lower()
        if '429' in error_str or 'too many requests' in error_str:
            log.warning('rate_limited')
            raise RateLimitError('Yahoo rate limit hit') from e
        log.error('yfinance_fetch_failed', error=str(e))
        raise FetchError(f"Failed to fetch data for {symbol}") from e
    
    if not _is_valid_ticker_response(info):
        log.warning('invalid_ticker_no_price_data', fields_returned= len(info))
        raise InvalidTickerError(f"'{symbol}' returned no price data - may be invalid or delisted")
    
    log.info("yfinance_fetch_success", info_fields=len(info), history_rows=len(history))

    clean_data = _build_clean_data(symbol,info,history,log)
    log.info("fetch_complete")
    return clean_data

if __name__ == '__main__':
    import asyncio
    from sigma.config import get_settings as _gs
    from sigma.logging import setup_logging
    import logging
    logging.getLogger("yfinance").setLevel(logging.ERROR)

    setup_logging(_gs())

    async def test():
        data = await fetch_ticker('AAPL')
        print("apple:", data)

        data = await fetch_ticker('<<')
        print('tcs:', data)

    asyncio.run(test())
