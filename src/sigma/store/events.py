"""The stored corporate-action stream.

The same window is re-fetched every day and is almost entirely unchanged, so
the write has to be idempotent: running it twice must leave the table exactly
as running it once did. That is what the primary key below buys.

Losing this table is not merely slow, the way losing a cache is. Day 31 decides
what is *new* by comparing today's fetch against what is stored, so an empty
table after a restart means either a silent gap or a burst of duplicate alerts.
It lives on the `/data` volume from Day 06 for that reason.
"""

import datetime as dt
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from sigma.domain import CorporateAction, EventDetail, Exchange
from sigma.logging import get_logger

logger = get_logger(__name__)

# (exchange, symbol, event_type, ex_date, raw). Exchange is in the key because
# the same action on a dual-listed company is two rows on purpose; ex_date is in
# it because a company can pay two dividends inside one window; and raw is in it
# because a company can pay two dividends on the *same day* and nothing else in
# either feed separates them. See CorporateAction.key.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS corporate_actions (
    exchange    TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    ex_date     TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    company     TEXT,
    isin        TEXT,
    record_date TEXT,
    detail      TEXT NOT NULL,
    raw         TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    PRIMARY KEY (exchange, symbol, event_type, ex_date, raw)
);
CREATE INDEX IF NOT EXISTS ix_corporate_actions_ex_date
    ON corporate_actions (ex_date);
"""

# Every statement is written out in full rather than assembled from fragments.
# Concatenating SQL at the call site is how an injection gets in even when
# today's inputs are all literals, and `ruff --select S` is right to say so.
_SELECT_MUTABLE = """
SELECT ticker, company, isin, record_date, detail FROM corporate_actions
WHERE exchange = ? AND symbol = ? AND event_type = ? AND ex_date = ? AND raw = ?
"""

_INSERT = """
INSERT INTO corporate_actions
    (exchange, symbol, event_type, ex_date, raw, ticker, company, isin,
     record_date, detail, first_seen, last_seen)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_TOUCH = """
UPDATE corporate_actions SET last_seen = ?
WHERE exchange = ? AND symbol = ? AND event_type = ? AND ex_date = ? AND raw = ?
"""

_UPDATE = """
UPDATE corporate_actions
SET ticker = ?, company = ?, isin = ?, record_date = ?, detail = ?, last_seen = ?
WHERE exchange = ? AND symbol = ? AND event_type = ? AND ex_date = ? AND raw = ?
"""

_BETWEEN = """
SELECT exchange, symbol, event_type, ex_date, ticker, company, isin,
       record_date, detail, raw
FROM corporate_actions WHERE ex_date BETWEEN ? AND ?
ORDER BY ex_date, exchange, symbol
"""

_BETWEEN_ON_EXCHANGE = """
SELECT exchange, symbol, event_type, ex_date, ticker, company, isin,
       record_date, detail, raw
FROM corporate_actions WHERE ex_date BETWEEN ? AND ? AND exchange = ?
ORDER BY ex_date, exchange, symbol
"""


@dataclass(frozen=True, slots=True)
class UpsertCounts:
    """What a refresh actually did. `unchanged` is the number that should be large."""

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class EventStore:
    """SQLite behind a domain-shaped interface. No caller writes SQL."""

    def __init__(self, path: Path, *, now: Callable[[], dt.datetime] = _utc_now) -> None:
        self._path = path
        # Injected so a test can assert on first_seen and last_seen without
        # sleeping. Day 10 does the same thing to the backoff clock.
        self._now = now
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        # TODO(day-12): WAL, busy_timeout and a shared connection land with the
        # cache, which is the day that has concurrent readers to justify them.
        return sqlite3.connect(self._path)

    def upsert_many(self, actions: Iterable[CorporateAction]) -> UpsertCounts:
        """Insert what is new, update what changed, and touch the rest.

        Re-running this over the same fetch is a no-op except for `last_seen`,
        which is the property that makes a daily re-fetch safe.
        """
        stamp = self._now().isoformat()
        inserted = updated = unchanged = 0

        with closing(self._connect()) as conn, conn:
            for action in actions:
                key = _key_row(action.key)
                values = (
                    action.ticker,
                    action.company,
                    action.isin,
                    action.record_date.isoformat() if action.record_date else None,
                    action.detail.model_dump_json(),
                )
                existing = conn.execute(_SELECT_MUTABLE, key).fetchone()

                if existing is None:
                    conn.execute(_INSERT, (*key, *values, stamp, stamp))
                    inserted += 1
                elif tuple(existing) == values:
                    # Same event, same content. last_seen still moves: "we saw
                    # it again today" is a different fact from "it changed".
                    conn.execute(_TOUCH, (stamp, *key))
                    unchanged += 1
                else:
                    conn.execute(_UPDATE, (*values, stamp, *key))
                    updated += 1

        counts = UpsertCounts(inserted=inserted, updated=updated, unchanged=unchanged)
        logger.info(
            "corpactions_stored",
            inserted=counts.inserted,
            updated=counts.updated,
            unchanged=counts.unchanged,
        )
        return counts

    def count(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) FROM corporate_actions").fetchone()
        return int(row[0])

    def between(
        self, start: dt.date, end: dt.date, *, exchange: Exchange | None = None
    ) -> tuple[CorporateAction, ...]:
        """Every stored event with an ex-date in [start, end], oldest first.

        ISO dates sort lexicographically, which is why they are stored as text
        rather than as a Julian day nobody can read in a shell.
        """
        params: list[str] = [start.isoformat(), end.isoformat()]
        sql = _BETWEEN
        if exchange is not None:
            sql = _BETWEEN_ON_EXCHANGE
            params.append(exchange.value)

        with closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return tuple(_to_action(row) for row in rows)


def _key_row(key: tuple[str, str, str, dt.date, str]) -> tuple[str, str, str, str, str]:
    exchange, symbol, event_type, ex_date, raw = key
    return (exchange, symbol, event_type, ex_date.isoformat(), raw)


def _to_action(row: tuple[str, ...]) -> CorporateAction:
    exchange, symbol, _event_type, ex_date, ticker, company, isin, record_date, detail, raw = row
    # event_type is a column because the primary key needs it and because
    # Day 31 filters on it in SQL. It is not read back into the model: the
    # detail already carries it, and one value with two sources of truth is
    # one too many.
    return CorporateAction(
        exchange=Exchange(exchange),
        symbol=symbol,
        ticker=ticker,
        company=company,
        isin=isin,
        detail=EventDetail.model_validate_json(detail),
        ex_date=dt.date.fromisoformat(ex_date),
        record_date=dt.date.fromisoformat(record_date) if record_date else None,
        raw=raw,
    )
