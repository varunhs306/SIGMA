"""Read back what `scripts/record_fixtures.py` recorded.

The split matters: the recorder is the only thing that writes `tests/fixtures/`
and this module is the only thing that reads it. Neither knows how to produce
the other's side, so a test cannot quietly invent a payload shape.

A replayed fixture is a *stub* - it answers, it does not assert. The two places
that need to know what was asked (`test_corpaction_providers.py` checking the
window and the Referer) keep using a hand-built handler, because a spy and a
stub are different tools and the recorded payload has no opinion about the
request that fetched it.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from sigma.domain import Exchange
from sigma.providers.yahoo import YahooProvider

FIXTURES = Path(__file__).resolve().parent / "fixtures"

_BAR_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


def load(relative: str) -> dict[str, Any]:
    """One fixture document, with the failure a missing file deserves."""
    path = FIXTURES / relative
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. Re-record it: uv run python scripts/record_fixtures.py --all"
        )
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def corpactions(exchange: Exchange) -> dict[str, Any]:
    return load(f"{exchange.value.lower()}_corporate_actions.json")


def corpaction_client(exchange: Exchange) -> httpx.AsyncClient:
    """A real AsyncClient that answers with the recorded rows and opens no socket."""
    records = corpactions(exchange)["records"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(httpx.codes.OK, json=records)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def yahoo(symbol: str) -> dict[str, Any]:
    return load(f"yahoo/{_slug(symbol)}.json")


def yahoo_payload(symbol: str) -> tuple[dict[str, Any], pd.DataFrame]:
    """The `(info, history)` pair exactly as `YahooProvider._fetch` returns it."""
    document = yahoo(symbol)
    bars = document["bars"]
    frame = pd.DataFrame(
        [[bar[column.lower()] for column in _BAR_COLUMNS] for bar in bars],
        columns=list(_BAR_COLUMNS),
        index=pd.to_datetime([bar["date"] for bar in bars]),
    )
    info: dict[str, Any] = document["info"]
    return info, frame


def yahoo_provider(symbol: str) -> YahooProvider:
    """The real provider with its one network method answering from disk.

    Subclassing the seam rather than patching `yfinance`: everything above
    `_fetch` - the symbol validation, the error translation, the mapper, the
    domain validators - is the real code under test.
    """
    info, history = yahoo_payload(symbol)

    class Replayed(YahooProvider):
        async def _fetch(self, symbol: str) -> tuple[dict[str, Any], pd.DataFrame]:
            return info, history

    return Replayed()


def recorded_at(document: dict[str, Any]) -> dt.date:
    return dt.datetime.fromisoformat(document["recorded_at"]).date()


def _slug(symbol: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in symbol).strip("_").lower()
