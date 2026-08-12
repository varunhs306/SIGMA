import asyncio
import random

from google import genai
from google.api_core import exceptions as google_exceptions
from google.genai import types

from sigma.config import settings
from sigma.logger import get_logger

logger = get_logger(__name__)

class AnalysisError(Exception):
    """Base exception for all analyzer failures"""

class GeminiRateLimitError(AnalysisError):
    """Gemini API rate limit hit (HTTP 429 / ResourceExhausted)"""

class GeminiUnavilableError(AnalysisError):
    """Gemini API returned a server error — safe to retry"""

client = genai.Client(api_key=settings.gemini_api_key)


GEN_CONFIG = types.GenerateContentConfig(
    temperature=0.3,
    max_output_tokens=1024,
)

async def _call_gemini_with_retry(prompt: str, max_retries: int =3):
    last_exception = None
    for attempt in range(max_retries):
        try:
            response = await client.aio.models.generate_content(
                model = "gemini-2.5-flash-lite",
                contents=prompt,
                config=GEN_CONFIG,
            )
            finish_reason = str(response.candidates[0].finish_reason)
            if finish_reason == 'FinishReason.MAX_TOKENS':
                logger.warning("response_truncated",finish_reason=finish_reason)
            elif finish_reason == 'FinishReason.SAFETY':
                logger.error("response_blocked_by_safety", finish_reason=finish_reason)
                raise AnalysisError('Gemini Blocked this response due to safety filters')
            if response.usage_metadata:
                logger.info(
                    "gemini_response_received",
                    prompt_tokens=response.usage_metadata.prompt_token_count,
                    response_tokens=response.usage_metadata.candidates_token_count,
                    context_tokens=response.usage_metadata.total_token_count,
                    attempt=attempt
                )
            return response.text
        except google_exceptions.ResourceExhausted as e:
            wait = 2 ** attempt
            logger.warning('gemini_rate_limited',attempt=attempt,wait_seconds=wait)
            await asyncio.sleep(wait)
            last_exception = e
        except (google_exceptions.InternalServerError,google_exceptions.ServiceUnavailable) as e:
            wait = 2 ** attempt
            logger.warning('gemini_server_error', attempt=attempt,wait_seconds=wait,error=str(e))
            await asyncio.sleep(wait)
            last_exception = e
        except google_exceptions.InvalidArgument as e:
            logger.error('gemini_invalid_argument', error=str(e))
            raise AnalysisError(f"Invalid request to Gemini: {e}") from e
        except google_exceptions.Unauthenticated as e:
            logger.error('gemini_auth_failed')
            raise AnalysisError('Gemini Auth failed Check your api key') from e
    logger.error('gemini_max_retries_exceeded', attempt=max_retries)
    raise GeminiRateLimitError("Gemini unavailable after max retries") from last_exception

def _build_prompt(data: dict) -> str:
    def fmt(value, prefix='', suffix='',decimals=2):
        if value is None:
            return 'N/A'
        if isinstance(value,float):
            return f"{prefix}{value:.{decimals}f}{suffix}"
        if isinstance(value,int):
            return f"{prefix}{value:,}{suffix}"
        return f"{prefix}{value}{suffix}"
    
    market_cap = data.get('market_cap')

    if market_cap and market_cap >= 1_000_000_000_000:
        market_cap_str = f"{market_cap / 1_000_000_000_000:.2f}T"
    elif market_cap and market_cap >= 1_000_000_000:
        market_cap_str = f"{market_cap / 1_000_000_000:.2f}B"
    else:
        market_cap_str = fmt(market_cap, prefix="$")
    
    price_change= data.get('price_change_30d')
    if price_change is not None and price_change > 0:
        price_change_str = f"+{price_change:.2f}%"
    elif price_change is not None:
        price_change_str = f"{price_change:.2f}%"
    else:
        price_change_str = 'N/A'

    return f"""You are a senior financial analyst. Analyze the following market data for {data.get('symbol')} ({data.get('company_name', 'Unknown')}).
=== MARKET DATA ===
Sector: {data.get('sector', 'N/A')}
Industry: {data.get('industry', 'N/A')}
Current Price: {fmt(data.get('current_price'), prefix='$')}
Market Cap: {market_cap_str}
P/E Ratio (Trailing): {fmt(data.get('trailing_pe'))}
P/E Ratio (Forward): {fmt(data.get('forward_pe'))}
Price-to-Book: {fmt(data.get('price_to_book'))}
52-Week High: {fmt(data.get('week_52_high'), prefix='$')}
52-Week Low: {fmt(data.get('week_52_low'), prefix='$')}
Today's Volume: {fmt(data.get('volume'))}
Average Volume (90d): {fmt(data.get('avg_volume'))}
Beta: {fmt(data.get('beta'))}
Dividend Yield: {fmt(data.get('dividend_yield'), suffix='%', decimals=4) if data.get('dividend_yield') else 'N/A'}
30-Day Price Change: {price_change_str}

Provide a structured analysis covering:
1. Valuation — is the stock cheap, fair, or expensive based on available metrics?
2. Key Risks — maximum 3 bullet points
3. Short-term Outlook — based on price trend and volume

Be concise. Do not give buy or sell recommendations. If a metric shows N/A, skip it and work with what is available.\n\n
Format your response using Telegram Markdown: use *text* for bold (not **text**), use - for bullet points. No headers with #."""

async def analyze_ticker(data: dict) -> str:
    symbol = data.get('symbol','UNKNOWN')
    log = logger.bind(ticker=symbol)

    log.info('analyzer_started')
    prompt = _build_prompt(data)
    log.debug('prompt_built',char_length=len(prompt))

    analysis = await _call_gemini_with_retry(prompt)
    if analysis is None:
        logger.error('analysis_returned_empty')
        raise AnalysisError('Gemini returned no Text')
    log.info('analyzer_complete',response_length=len(analysis))
    return analysis


if __name__ == '__main__':
    import asyncio
    from sigma.logger import setup_logger
    from sigma.fetcher import fetch_ticker

    setup_logger()
    async def test():
        data = await fetch_ticker('AAPL')
        analysis = await analyze_ticker(data)
        print("\n---------ANalysis---------------")
        print(analysis)
    asyncio.run(test())

