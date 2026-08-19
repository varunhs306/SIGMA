from telegram.ext import Application, CommandHandler, MessageHandler, filters

from sigma.composition import build_handlers
from sigma.config import get_settings
from sigma.logging import setup_logging


def main() -> None:
    settings = get_settings()
    setup_logging(settings)

    handlers = build_handlers()

    app = Application.builder().token(settings.telegram_bot_token.get_secret_value()).build()

    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("help", handlers.help))
    app.add_handler(CommandHandler("price", handlers.price))
    app.add_handler(CommandHandler("analyze", handlers.analyze))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.unknown_text))
    app.add_error_handler(handlers.on_error)

    app.run_polling()


if __name__ == "__main__":
    main()
