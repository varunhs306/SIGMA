import uuid
from typing import Any

import structlog


def new_run(**fields: Any) -> str:
    structlog.contextvars.clear_contextvars()
    run_id = str(uuid.uuid4())[:8]
    structlog.contextvars.bind_contextvars(run_id=run_id, **fields)
    return run_id


def bind_run(**fields: Any) -> None:
    structlog.contextvars.bind_contextvars(**fields)
