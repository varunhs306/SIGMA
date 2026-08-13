import asyncio
import re
import time
from typing import Optional

import yfinance as yf
from sigma.logger import get_logger
from sigma.config import get_settings
logger = get_logger(__name__)

class FetchError(Exception):
    "Base exception for all fetcher failures"
class InvalidTickerError(FetchError):
    "Ticker symbol is invalid or has no data on Yahoo Finance"
class RateLimitError(FetchError):
    "Yahoo Finance is throttling our requests"

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

def _safe_get(data: dict, key: str, default=None):
    value = data.get(key,default)
    if value is None:
        logger.warning("missing_field", field=key)
        return default
    return value

def _build_clean_data(symbol: str, info: dict, history) -> dict:
    price_change_30d = 0

    if history is not None and not history.empty:
        first_close = history['Close'].iloc[0]
        last_close = history['Close'].iloc[-1]
        price_change_30d = round(((last_close - first_close) / first_close) * 100, 2)

    return {
        "symbol":symbol,
        "company_name":_safe_get(info,"longName"),
        "current_price":_safe_get(info,"currentPrice"),
        "market_cap":_safe_get(info,"marketCap"),
        "trailing_pe":_safe_get(info,"trailingPE"),
        "forward_pe":_safe_get(info,"forwardPE"),
        "price_to_book":_safe_get(info,"priceToBook"),
        "week_52_high":_safe_get(info,"fiftyTwoWeekHigh"),
        "week_52_low":_safe_get(info,"fiftyTwoWeekLow"),
        "volume":_safe_get(info,"volume"),
        "avg_volume":_safe_get(info,"averageVolume"),
        "beta":_safe_get(info,"beta"),
        "dividend_yield":_safe_get(info,"dividendYield"),
        "sector":_safe_get(info,"sector"),
        "industry":_safe_get(info,"industry"),
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

    clean_data = _build_clean_data(symbol,info,history)
    log.info("fetch_complete")
    return clean_data

if __name__ == '__main__':
    import asyncio
    from sigma.logger import setup_logger
    import logging
    logging.getLogger("yfinance").setLevel(logging.ERROR)

    setup_logger()

    async def test():
        data = await fetch_ticker('AAPL')
        print("apple:", data)

        data = await fetch_ticker('<<')
        print('tcs:', data)

    asyncio.run(test())
