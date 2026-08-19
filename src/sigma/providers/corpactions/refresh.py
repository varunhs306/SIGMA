"""Fetch a window, normalise it, store it. Backfill and incremental are the same call.

There is no separate backfill path. A three-year backfill is this function with
a wider window, and the daily job is this function with a narrow one, because
the upsert makes overlap free. A second code path for the initial load is a
second code path to keep correct.
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field

from sigma.exceptions import ProviderError
from sigma.logging import get_logger
from sigma.providers.corpactions.base import CorporateActionProvider
from sigma.store import EventStore, UpsertCounts

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RefreshReport:
    """Per-exchange outcome. `error` is set when that exchange failed."""

    exchange: str
    fetched: int = 0
    counts: UpsertCounts = field(default_factory=UpsertCounts)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


async def refresh(
    providers: Sequence[CorporateActionProvider],
    store: EventStore,
    start: dt.date,
    end: dt.date,
) -> tuple[RefreshReport, ...]:
    """Refresh every provider. One failing exchange must not cost the others.

    Returns a report per provider rather than raising, because "NSE is down and
    BSE is fine" is a normal Tuesday and the caller needs both facts.
    """
    reports: list[RefreshReport] = []

    for provider in providers:
        exchange = provider.exchange.value
        try:
            actions = await provider.fetch(start, end)
        except ProviderError as e:
            logger.warning("refresh_failed", exchange=exchange, error=str(e))
            reports.append(RefreshReport(exchange=exchange, error=str(e)))
            continue

        counts = store.upsert_many(actions)
        reports.append(RefreshReport(exchange=exchange, fetched=len(actions), counts=counts))
        logger.info(
            "refresh_complete",
            exchange=exchange,
            fetched=len(actions),
            inserted=counts.inserted,
            updated=counts.updated,
            unchanged=counts.unchanged,
        )

    return tuple(reports)
