"""NSE bulk corporate actions.

Verified live against a 01-08-2026 to 30-09-2026 window: 316 records, every
event type in one call, ISIN supplied.

Two things about this endpoint that cost time to find:

1. **The dates are mandatory.** Omitting them returns 20 records from a
   roughly two-day default window with a 200 status, which reads as success.
2. `subject=Split` and friends narrow the response to one event type. Sending
   no type filter at all is what returns everything.
"""

import datetime as dt
from typing import Any

import httpx

from sigma.domain import CorporateAction, Exchange
from sigma.logging import get_logger
from sigma.providers.corpactions.base import parse_date, text_or_none
from sigma.providers.corpactions.http import get_json
from sigma.providers.corpactions.normalise import normalise

logger = get_logger(__name__)

_URL = "https://www.nseindia.com/api/corporates-corporateActions"
# NSE answers a default python-httpx user agent with an interstitial rather than
# JSON. No cookie warm-up is needed as of the day this was written - a bare GET
# with a browser UA returns 200 - but that is an observation, not a contract.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions",
}
_DATE_IN = "%d-%m-%Y"
_DATE_OUT = ("%d-%b-%Y",)


class NseProvider:
    """Satisfies `CorporateActionProvider`."""

    exchange = Exchange.NSE

    def __init__(self, client: httpx.AsyncClient) -> None:
        # Constructor injection again, for the same reason as Day 08 and one
        # more: a test supplies a MockTransport client, so no test in this
        # suite can reach the network even by accident.
        self._client = client

    async def fetch(self, start: dt.date, end: dt.date) -> tuple[CorporateAction, ...]:
        params = {
            "index": "equities",
            "from_date": start.strftime(_DATE_IN),
            "to_date": end.strftime(_DATE_IN),
        }
        rows = await get_json(
            self._client, _URL, params=params, headers=_HEADERS, exchange=self.exchange
        )

        actions: list[CorporateAction] = []
        rejected = 0
        for row in rows:
            action = _to_action(row)
            if action is None:
                rejected += 1
                continue
            actions.append(action)

        logger.info(
            "corpactions_fetched",
            exchange=self.exchange.value,
            rows=len(rows),
            kept=len(actions),
            rejected=rejected,
            start=start.isoformat(),
            end=end.isoformat(),
        )
        return tuple(actions)


def _to_action(row: dict[str, Any]) -> CorporateAction | None:
    symbol = text_or_none(row.get("symbol"))
    ex_date = parse_date(row.get("exDate"), *_DATE_OUT)
    raw = text_or_none(row.get("subject"))
    # An event with no ex-date cannot be alerted on and cannot form the store's
    # key, so it is dropped - loudly, and counted by the caller.
    if symbol is None or ex_date is None or raw is None:
        logger.warning("corpaction_row_unusable", exchange="NSE", row=row)
        return None

    return CorporateAction(
        exchange=Exchange.NSE,
        symbol=symbol,
        ticker=f"{symbol}{Exchange.NSE.suffix}",
        company=text_or_none(row.get("comp")),
        isin=text_or_none(row.get("isin")),
        detail=normalise(raw),
        ex_date=ex_date,
        record_date=parse_date(row.get("recDate"), *_DATE_OUT),
        raw=raw,
    )
