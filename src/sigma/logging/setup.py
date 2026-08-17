import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

import structlog
from structlog.typing import Processor

from sigma.logging.redaction import redact_processor, register_secret

_CONFIGURED = False

_THIRD_PARTY_LEVELS = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "telegram": logging.INFO,
    "yfinance": logging.ERROR,
    "urllib3": logging.WARNING,
}


def setup_logging(settings: Any) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    register_secret(settings.gemini_api_key.get_secret_value())
    register_secret(settings.telegram_bot_token.get_secret_value())

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        redact_processor,
    ]

    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        settings.log_file,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
    )
    file_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared,
        )
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(),
            foreign_pre_chain=shared,
        )
    )

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    for name, level in _THIRD_PARTY_LEVELS.items():
        logging.getLogger(name).setLevel(level)

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
