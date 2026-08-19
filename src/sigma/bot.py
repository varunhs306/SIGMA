from collections.abc import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from sigma.domain import TickerSnapshot
from sigma.exceptions import SigmaError
from sigma.logging import bind_run, get_logger, new_run
from sigma.providers import MarketDataProvider

logger = get_logger(__name__)

# TODO(day-25): this becomes an LLMProvider protocol with its own error taxonomy
# and a degraded mode. Until then a callable is the honest description of what
# the bot needs: something that turns a snapshot into prose.
Analyser = Callable[[TickerSnapshot], Awaitable[str]]


def fmt(val: float | int | None, prefix: str = "", suffix: str = "", decimals: int = 2) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, float):
        return f"{prefix}{val:.{decimals}f}{suffix}"
    return f"{prefix}{val:,}{suffix}"


TRILLION = 1_000_000_000_000
BILLION = 1_000_000_000


def fmt_market_cap(market_cap: int | None) -> str:
    if market_cap is None:
        return "N/A"
    if market_cap >= TRILLION:
        return f"${market_cap / TRILLION:.2f}T"
    if market_cap >= BILLION:
        return f"${market_cap / BILLION:.2f}B"
    return f"${market_cap:,}"


def fmt_change(change: float | None) -> str:
    if change is None:
        return "N/A"
    if change > 0:
        return f"+{change:.2f}%"
    return f"{change:.2f}%"


class Handlers:
    """The Telegram interface. Owns no data source and imports no vendor SDK.

    Both collaborators arrive through the constructor, so a test builds this
    object with fakes and never patches a module attribute. The composition
    root is the only place that knows which implementations are real.
    """

    def __init__(self, provider: MarketDataProvider, analyse: Analyser) -> None:
        self._provider = provider
        self._analyse = analyse

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None:
            return
        user = update.effective_user
        new_run(user_id=user.id if user else None, command="start")
        logger.info("request_start")

        welcome_text = (
            "👋 Welcome to SAGE Bot — your financial analysis assistant.\n\n"
            "Commands:\n"
            "  /price <TICKER>   — Get the current price and key stats\n"
            "  /analyze <TICKER> — Get an AI-powered analysis from Gemini\n"
            "  /help             — Show this message again\n\n"
            "Example: /analyze AAPL"
        )
        await message.reply_text(welcome_text)
        logger.info("response_sent")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None:
            return
        user = update.effective_user
        new_run(user_id=user.id if user else None, command="help")
        logger.info("request_start")

        await message.reply_text("SAGE BOT= analysis\n\n")
        logger.info("response_sent")

    async def price(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None:
            return
        user = update.effective_user
        new_run(user_id=user.id if user else None, command="price")
        logger.info("request_start")

        if not context.args:
            logger.warning("missing_argument")
            await message.reply_text("Usage: /price <TICKER> \nExample: /price AAPL")
            return
        symbol = context.args[0].upper()
        bind_run(ticker=symbol)
        logger.info("processing_request")

        await message.reply_text(f"Fetching data for {symbol}...")

        try:
            snapshot = await self._provider.get_snapshot(symbol)

        except SigmaError as e:
            # Expected failure. The exception already knows what to tell the user.
            logger.warning("request_failed", error_type=type(e).__name__, error=str(e))
            await message.reply_text(e.user_message)
            return

        except Exception:
            # BUG PATH. An unmodelled failure is a defect in the exception hierarchy,
            # not a user error. logger.exception() keeps the traceback.
            logger.exception("unhandled_exception")
            await message.reply_text("Something went wrong. Please try again.")
            return

        quote = snapshot.quote
        reply = (
            # `or symbol`, not dict.get(key, symbol): the key was always present and
            # always None, so the default never fired and the header read "None (AAPL)".
            f"{snapshot.profile.name or symbol} ({symbol})"
            "\n"
            f"Price: {fmt(quote.price, prefix='$')}\n"
            f"Market Cap:{fmt_market_cap(quote.market_cap)}\n"
            f"P/E Ratio:{fmt(quote.trailing_pe)}\n"
            f"52W High:{fmt(quote.week_52_high, prefix='$')}\n"
            f"52W Low:{fmt(quote.week_52_low, prefix='$')}\n"
            f"30D Change:{fmt_change(snapshot.price_change_30d)}"
        )
        await message.reply_text(reply)
        logger.info("response_sent")

    async def analyze(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None:
            return
        user = update.effective_user
        new_run(user_id=user.id if user else None, command="analyze")
        logger.info("request_start")

        if not context.args:
            logger.warning("missing_argument")
            await message.reply_text("Usage:/analyze <TICKER>\nExample: /analyze AAPL")
            return
        symbol = context.args[0].upper()
        bind_run(ticker=symbol)
        logger.info("processing_request")
        await message.reply_text(f"Analyzing {symbol}....this may take few seconds")

        try:
            snapshot = await self._provider.get_snapshot(symbol)

        except SigmaError as e:
            logger.warning("request_failed", error_type=type(e).__name__, error=str(e))
            await message.reply_text(e.user_message)
            return

        except Exception:
            logger.exception("unhandled_exception")
            await message.reply_text("Something went wrong. Please try again.")
            return

        try:
            analysis = await self._analyse(snapshot)

        except SigmaError as e:
            # The analyser raises LLMError subclasses, which SigmaError covers.
            logger.warning("request_failed", error_type=type(e).__name__, error=str(e))
            await message.reply_text(e.user_message)
            return

        except Exception:
            logger.exception("unhandled_exception")
            await message.reply_text("Something went wrong. Please try again.")
            return
        header = f"📈*{symbol}* Analysis\n\n"
        await message.reply_text(header + analysis, parse_mode="Markdown")
        logger.info("response_sent", response_length=len(analysis))

    async def unknown_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None:
            return
        user = update.effective_user
        new_run(user_id=user.id if user else None, command="unknown")
        logger.info("unknown_message_received", text_length=len(message.text or ""))
        await message.reply_text("I only respond to commands.")

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error(
            "unhandled_telegram_error",
            error=str(context.error),
            update_type=type(update).__name__,
        )
