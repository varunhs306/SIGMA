from typing import Any

from sigma.logging.context import bind_run, new_run
from sigma.logging.setup import setup_logging

__all__ = ["bind_run", "get_logger", "new_run", "setup_logging"]


def get_logger(name: str) -> Any:
    import structlog

    return structlog.get_logger(name)
