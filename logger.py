import logging
import os
import structlog
from logging.handlers import RotatingFileHandler
from config import settings

def setup_logger():
    os.makedirs('logs', exist_ok=True)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)

    file_handler = RotatingFileHandler(
        "logs/sage.log",
        maxBytes=5* 1024 *1024,
        backupCount=3
    )
    file_handler.setLevel(logging.DEBUG)

    console_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(),
    )
    file_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer()
    )
    console_handler.setFormatter(console_formatter)
    file_handler.setFormatter(file_formatter)

    rootlogger = logging.getLogger()
    rootlogger.setLevel(getattr(logging, settings.log_level.upper()))
    rootlogger.addHandler(console_handler)
    rootlogger.addHandler(file_handler)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt='iso'),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
def get_logger(name: str):
    return structlog.get_logger(name)

if __name__ == '__main__':
    setup_logger()
    log = get_logger(__name__)
    log.error("logger_test",status="working")