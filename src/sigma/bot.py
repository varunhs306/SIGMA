from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from sigma.config import get_settings
from sigma.logger import get_logger
from sigma.exceptions import SigmaError
from sigma.fetcher import fetch_ticker
import telegramify_markdown
from sigma.analyzer import analyze_ticker

logger = get_logger(__name__)

def fmt(val,prefix='',suffix='',decimals=2):
    if val is None:
        return 'N/A'
    if isinstance(val,float):
        return f"{prefix}{val:.{decimals}f}{suffix}"
    if isinstance(val,int):
        return f"{prefix}{val:,}{suffix}"
    return f"{prefix}{val}{suffix}"

TRILLION = 1_000_000_000_000
BILLION = 1_000_000_000
def  fmt_market_cap(market_cap):
    if market_cap is None:
        return 'N/A'
    if market_cap >= TRILLION:
        return f"${market_cap/TRILLION:.2f}T"
    if market_cap >= BILLION:
        return f"${market_cap/BILLION:.2f}B"
    return f"${market_cap:,}"
def fmt_change(change):
    if change is None:
        return "N/A"
    if change > 0:
        return f'+{change:.2f}%'
    return f'{change:.2f}%'

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log = logger.bind(user_id=update.effective_user.id, command='start')
    log.info('command_received')

    welcome_text = (
        "👋 Welcome to SAGE Bot — your financial analysis assistant.\n\n"
        "Commands:\n"
        "  /price <TICKER>   — Get the current price and key stats\n"
        "  /analyze <TICKER> — Get an AI-powered analysis from Gemini\n"
        "  /help             — Show this message again\n\n"
        "Example: /analyze AAPL"
    )
    await update.message.reply_text(welcome_text)
    log.info('response_sent')

async def price_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log = logger.bind(user_id = update.effective_user.id, command='price')
    log.info('command_received')

    if not context.args:
        log.warning('missing_argument')
        await update.message.reply_text('Usage: /price <TICKER> \nExample: /price AAPL')
        return
    symbol = context.args[0].upper()
    log = log.bind(ticker=symbol)
    log.info('processing_request')

    await update.message.reply_text(f"Fetching data for {symbol}...")

    try:
        data = await fetch_ticker(symbol)

    except SigmaError as e:
        # Expected failure. The exception already knows what to tell the user.
        log.warning("request_failed", error_type=type(e).__name__, error=str(e))
        await update.message.reply_text(e.user_message)
        return

    except Exception:
        # BUG PATH. An unmodelled failure is a defect in the exception hierarchy,
        # not a user error. log.exception() keeps the traceback.
        log.exception("unhandled_exception")
        await update.message.reply_text("Something went wrong. Please try again.")
        return

    message = (
        f"{data.get('company_name', symbol)} ({symbol})"
        "\n"
        f"Price: {fmt(data.get('current_price'), prefix='$')}\n"
        f"Market Cap:{fmt_market_cap(data.get('market_cap'))}\n"
        f"P/E Ratio:{fmt(data.get('trailing_pe'))}\n"
        f"52W High:{fmt(data.get('week_52_high'),prefix='$')}\n"
        f"52W Low:{fmt(data.get('week_52_low'),prefix='$')}\n"
        f"30D Change:{fmt_change(data.get('price_change_30d'))}"
    )
    await update.message.reply_text(message)
    log.info('response_sent')

async def analyze_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log = logger.bind(user_id=update.effective_user.id,command='analyze')
    log.info('command_received')

    if not context.args:
        log.warning('missing_argument')
        await update.message.reply_text(
            "Usage:/analyze <TICKER>\nExample: /analyze AAPL"
        )
        return
    symbol = context.args[0].upper()
    log = log.bind(ticker=symbol)
    log.info('processing_request')
    await update.message.reply_text(
        f"Analyzing {symbol}....this may take few seconds"
    )
    
    try:
        data = await fetch_ticker(symbol)
    
    except SigmaError as e:
        log.warning("request_failed", error_type=type(e).__name__, error=str(e))
        await update.message.reply_text(e.user_message)
        return

    except Exception:
        log.exception("unhandled_exception")
        await update.message.reply_text("Something went wrong. Please try again.")
        return

    try:
        analysis = await analyze_ticker(data)

    except SigmaError as e:
        # analyze_ticker now raises LLMError subclasses, which SigmaError covers.
        log.warning("request_failed", error_type=type(e).__name__, error=str(e))
        await update.message.reply_text(e.user_message)
        return

    except Exception:
        log.exception('unhandled_exception')
        await update.message.reply_text("Something went wrong. Please try again.")
        return
    header = f"📈*{symbol}* Analysis\n\n"
    await update.message.reply_text(header + analysis,parse_mode='Markdown')
    log.info('response_sent',response_length=len(analysis))

async def unknown_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log = logger.bind(user_id=update.effective_user.id)
    log.info('unkown_message_received', text_length=len(update.message.text))
    await update.message.reply_text("I only respond to commands.")
async def help_handler(update: Update,context: ContextTypes.DEFAULT_TYPE) -> None:
    log = logger.bind(user_id=update.effective_user.id,command='help')
    log.info('command_received')

    await update.message.reply_text(
        "SAGE BOT= analysis\n\n"

    )
    log.info('response_sent')
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(
        "unhandled_telegram_error",
        error=str(context.error),
        update_type=type(update).__name__,
    )