from telegram.ext import Application, CommandHandler, MessageHandler, filters

from sigma.bot import (
    analyze_handler,
    error_handler,
    help_handler,
    price_handler,
    start_handler,
    unknown_text_handler,
)
from sigma.config import get_settings
from sigma.logging import setup_logging


def main():
    settings = get_settings()
    setup_logging(settings)

    app = Application.builder().token(settings.telegram_bot_token.get_secret_value()).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("price", price_handler))
    app.add_handler(CommandHandler("analyze", analyze_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text_handler))
    app.add_error_handler(error_handler)

    app.run_polling()


if __name__ == "__main__":
    main()
