from telegram.ext import Application,CommandHandler,MessageHandler,filters
from sigma.config import settings
from sigma.logger import setup_logger

from sigma.bot import (
    start_handler,
    help_handler,
    price_handler,
    analyze_handler,
    unknown_text_handler,
    error_handler,
)

def main():
    setup_logger()

    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_handler(CommandHandler('start', start_handler))
    app.add_handler(CommandHandler('help', help_handler))
    app.add_handler(CommandHandler('price', price_handler))
    app.add_handler(CommandHandler('analyze', analyze_handler))

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        unknown_text_handler
    ))
    app.add_error_handler(error_handler)

    app.run_polling()

if __name__ == '__main__':
    main()