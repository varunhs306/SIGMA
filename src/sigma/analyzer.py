import asyncio
import random
from functools import lru_cache

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from sigma.config import get_settings
from sigma.domain import TickerSnapshot
from sigma.exceptions import (
    LLMAuthError,
    LLMError,
    LLMInvalidResponse,
    LLMRateLimited,
    LLMUnavailable,
)
from sigma.logging import get_logger

logger = get_logger(__name__)


def _translate(err: genai_errors.APIError) -> LLMError:
    code = err.code
    if code == 429:
        return LLMRateLimited(str(err))
    if code in (401, 403):
        return LLMAuthError(str(err))
    if code is not None and 500 <= code < 600:
        return LLMUnavailable(str(err))
    return LLMError(str(err))


@lru_cache(maxsize=1)
def _get_client() -> genai.Client:
    return genai.Client(api_key=get_settings().gemini_api_key.get_secret_value())


GEN_CONFIG = types.GenerateContentConfig(
    temperature=0.3,
    max_output_tokens=1024,
)


async def _call_gemini_with_retry(prompt: str, max_retries: int | None = None) -> str | None:
    settings = get_settings()
    max_retries = max_retries or settings.llm_max_retries
    gen_config = types.GenerateContentConfig(
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
    )

    for attempt in range(max_retries):
        try:
            response = await _get_client().aio.models.generate_content(
                model=settings.llm_model,
                contents=prompt,
                config=gen_config,
            )
        except genai_errors.APIError as e:
            err = _translate(e)
            if not err.retryable or attempt == max_retries - 1:
                raise err from e
            wait = 2**attempt + random.uniform(0, 1)  # noqa: S311
            logger.info(
                "gemini_retrying", attempt=attempt, wait_seconds=round(wait, 2), code=e.code
            )
            await asyncio.sleep(wait)
            continue

        if not response.candidates:
            raise LLMInvalidResponse("Gemini returned no candidates")

        finish_reason = str(response.candidates[0].finish_reason)
        if finish_reason == "FinishReason.MAX_TOKENS":
            raise LLMInvalidResponse("Gemini response truncated at max_output_tokens")
        if finish_reason == "FinishReason.SAFETY":
            raise LLMInvalidResponse("Gemini blocked this response at the safety layer")

        if response.usage_metadata:
            logger.info(
                "gemini_response_received",
                prompt_tokens=response.usage_metadata.prompt_token_count,
                response_tokens=response.usage_metadata.candidates_token_count,
                context_tokens=response.usage_metadata.total_token_count,
                attempt=attempt,
            )
        return response.text

    # Unreachable while max_retries >= 1, which Settings enforces. Annotating the
    # return type is what surfaced the path at all: without it, a zero-iteration
    # loop returned None to a caller that expects a string.
    raise LLMError("gemini retry loop ended without a response")


def _build_prompt(snapshot: TickerSnapshot) -> str:
    def fmt(
        value: float | int | None, prefix: str = "", suffix: str = "", decimals: int = 2
    ) -> str:
        if value is None:
            return "N/A"
        if isinstance(value, float):
            return f"{prefix}{value:.{decimals}f}{suffix}"
        return f"{prefix}{value:,}{suffix}"

    quote = snapshot.quote
    profile = snapshot.profile

    market_cap = quote.market_cap
    if market_cap is None:
        market_cap_str = "N/A"
    elif market_cap >= 1_000_000_000_000:
        market_cap_str = f"{market_cap / 1_000_000_000_000:.2f}T"
    elif market_cap >= 1_000_000_000:
        market_cap_str = f"{market_cap / 1_000_000_000:.2f}B"
    else:
        market_cap_str = fmt(market_cap, prefix="$")

    change = snapshot.price_change_30d
    if change is None:
        price_change_str = "N/A"
    else:
        price_change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"

    # `or "Unknown"`, not dict.get(key, "Unknown"): the key was always present and
    # always None, so the default never fired and the prompt read "Sector: None".
    return f"""You are a senior financial analyst. Analyze the following market data for {snapshot.symbol} ({profile.name or "Unknown"}).
=== MARKET DATA ===
Sector: {profile.sector or "N/A"}
Industry: {profile.industry or "N/A"}
Current Price: {fmt(quote.price, prefix="$")}
Market Cap: {market_cap_str}
P/E Ratio (Trailing): {fmt(quote.trailing_pe)}
P/E Ratio (Forward): {fmt(quote.forward_pe)}
Price-to-Book: {fmt(quote.price_to_book)}
52-Week High: {fmt(quote.week_52_high, prefix="$")}
52-Week Low: {fmt(quote.week_52_low, prefix="$")}
Today's Volume: {fmt(quote.volume)}
Average Volume (90d): {fmt(quote.avg_volume)}
Beta: {fmt(quote.beta)}
Dividend Yield: {fmt(quote.dividend_yield, suffix="%", decimals=4)}
30-Day Price Change: {price_change_str}

Provide a structured analysis covering:
1. Valuation - is the stock cheap, fair, or expensive based on available metrics?
2. Key Risks - maximum 3 bullet points
3. Short-term Outlook - based on price trend and volume

Be concise. Do not give buy or sell recommendations. If a metric shows N/A, skip it and work with what is available.

Format your response using Telegram Markdown: use *text* for bold (not **text**), use - for bullet points. No headers with #."""


async def analyze_ticker(snapshot: TickerSnapshot) -> str:
    log = logger.bind(ticker=snapshot.symbol)

    log.info("analyzer_started")
    prompt = _build_prompt(snapshot)
    log.debug("prompt_built", char_length=len(prompt))

    analysis = await _call_gemini_with_retry(prompt)
    if analysis is None:
        logger.error("analysis_returned_empty")
        raise LLMInvalidResponse("Gemini returned no Text")
    log.info("analyzer_complete", response_length=len(analysis))
    return analysis


if __name__ == "__main__":
    import asyncio

    from sigma.config import get_settings as _gs
    from sigma.fetcher import fetch_ticker
    from sigma.logging import setup_logging

    setup_logging(_gs())

    async def test() -> None:
        data = await fetch_ticker("AAPL")
        analysis = await analyze_ticker(data)
        print("\n---------ANalysis---------------")
        print(analysis)

    asyncio.run(test())
