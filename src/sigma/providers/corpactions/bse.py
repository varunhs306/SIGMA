"""BSE bulk corporate actions.

Verified live against a 20260801 to 20260930 window: 651 records, every event
type in one call, no ISIN anywhere in the response.

Two things about this endpoint that cost time to find:

1. **It returns 301 without a `Referer` header**, and the body is empty, so a
   client that does not follow redirects reports nothing rather than an error.
2. `Purposecode=P26` and similar narrow the response to one event type. Leaving
   every filter parameter blank is what returns the whole calendar.

And one thing about the *response*: **`short_name` is not a yfinance ticker.**
`JOJO` and `KIRLPNU` look like symbols and are not - yfinance addresses BSE by
numeric scrip code, so `531910.BO` is right and `JOJO.BO` resolves to nothing.
Mapping from `short_name` fails silently on every BSE row, which produces an
empty result set rather than an error.
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

_URL = "https://api.bseindia.com/BseIndiaAPI/api/DefaultData/w"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    # Load-bearing. Without it the API answers 301 with an empty body.
    "Referer": "https://www.bseindia.com/",
}
_DATE_IN = "%Y%m%d"
# 'exdate' is the compact one and 'Ex_date' the readable one; both are sent and
# either can be blank, so both formats are accepted for both fields.
_DATE_OUT = ("%Y%m%d", "%d %b %Y")


class BseProvider:
    """Satisfies `CorporateActionProvider`."""

    exchange = Exchange.BSE

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch(self, start: dt.date, end: dt.date) -> tuple[CorporateAction, ...]:
        params = {
            "Fdate": start.strftime(_DATE_IN),
            "TDate": end.strftime(_DATE_IN),
            "ddlcategorys": "E",
            "ddlindustrys": "",
            "scripcode": "",
            "segment": "0",
            "strSearch": "S",
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
    scrip = row.get("scrip_code")
    # The scrip code arrives as an int and is an identifier, not a quantity.
    symbol = text_or_none(str(scrip)) if isinstance(scrip, int | str) else None
    ex_date = parse_date(row.get("exdate"), *_DATE_OUT) or parse_date(
        row.get("Ex_date"), *_DATE_OUT
    )
    raw = text_or_none(row.get("Purpose"))
    if symbol is None or ex_date is None or raw is None:
        logger.warning("corpaction_row_unusable", exchange="BSE", row=row)
        return None

    return CorporateAction(
        exchange=Exchange.BSE,
        symbol=symbol,
        # scrip code, never short_name - see the module docstring.
        ticker=f"{symbol}{Exchange.BSE.suffix}",
        company=text_or_none(row.get("long_name")),
        # BSE does not send one. Day 08b declines to fetch a scrip master to
        # invent it, because nothing downstream joins on it.
        isin=None,
        detail=normalise(raw),
        ex_date=ex_date,
        record_date=parse_date(row.get("RD_Date"), *_DATE_OUT),
        raw=raw,
    )
