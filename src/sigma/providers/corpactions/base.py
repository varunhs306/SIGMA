"""The bulk-calendar protocol, and the row helpers both feeds need.

`MarketDataProvider` answers one question about one company. This protocol
answers one question about *every* company on an exchange, which is a different
shape with different consequences: two HTTP requests cover both Indian
exchanges for a date window, where the per-ticker equivalent would be thousands.

**No cross-exchange deduplication.** A dual-listed company produces one row per
exchange - Kirloskar Pneumatic is BSE `505283` and NSE `KIRLPNU` for the same
2-for-1 split - and both are reported. Joining on ISIN would need a BSE scrip
master to supply the ISIN that BSE's own response omits, and ex-dates can
legitimately differ between exchanges for the same action, so merging would
sometimes be actively wrong.
"""

import datetime as dt
from typing import Any, Protocol, runtime_checkable

from sigma.domain import CorporateAction, Exchange

# Both feeds spell "no value" as a dash, an empty string, or a null.
_ABSENT = frozenset({"", "-", "--", "na", "n/a", "none", "null"})


@runtime_checkable
class CorporateActionProvider(Protocol):
    """Every corporate action on one exchange, for one date window.

    The window is a required argument, not an option with a default. NSE's
    endpoint accepts the request without dates and answers with a two-day
    default window, which looks exactly like success - 20 rows instead of 316 -
    so the only safe design is one that cannot express the call.
    """

    exchange: Exchange

    async def fetch(self, start: dt.date, end: dt.date) -> tuple[CorporateAction, ...]:
        """Raise a ProviderError subclass on failure, never return a partial silently."""
        ...


def text_or_none(value: Any) -> str | None:
    """Free text -> a string with content, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return None if text.lower() in _ABSENT else text


def parse_date(value: Any, *formats: str) -> dt.date | None:
    """First format that fits wins. An unparseable date is None, not today."""
    text = text_or_none(value)
    if text is None:
        return None
    for fmt in formats:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
