from sigma.logging.context import bind_run, new_run
from sigma.logging.setup import setup_logging

__all__ = ["setup_logging", "new_run", "bind_run", "get_logger"]


def get_logger(name: str):
    import structlog
    return structlog.get_logger(name)
