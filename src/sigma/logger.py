import logging
import os
import structlog
from logging.handlers import RotatingFileHandler
from sigma.config import get_settings

def setup_logger():
    settings = get_settings()
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)

    file_handler = RotatingFileHandler(
        settings.log_file,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
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
    rootlogger.setLevel(settings.log_level)
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