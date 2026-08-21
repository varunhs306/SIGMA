"""Record the payloads the test suite replays. Run by hand, never by pytest.

    uv run python scripts/record_fixtures.py --all

Everything under `tests/fixtures/` is the output of this script and nothing
else. Hand-editing a fixture is how a suite ends up asserting against a payload
the upstream never sent - the whole point of recording is that no human wrote
the bytes.

Two properties are deliberate:

**The recorder drives the real providers.** It does not rebuild the URL, the
params or the headers; it hands `NseProvider` a client whose transport keeps a
copy of what went over the wire. A fixture therefore cannot encode a request
that production does not make, which is the failure mode that makes recorded
tests worse than no tests.

**The corporate-action payloads are trimmed, the Yahoo ones are not.** A
two-month exchange window is ~1000 rows of near-identical dividends; a few rows
per event type cover every mapping branch at a twentieth of the size. Yahoo's
`info` is kept whole because its 185 keys *are* the thing under test - a
renamed key is exactly what a trimmed copy would hide.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any, cast

import httpx
import pandas as pd

from sigma.domain import CorporateAction, Exchange
from sigma.providers.corpactions import BseProvider, NseProvider
from sigma.providers.yahoo import YahooProvider

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

# Enough rows per event type to cover the mapping branches and the absent-value
# spellings, few enough that a reviewer can read the file.
ROWS_PER_EVENT_TYPE = 3

# Two months around the recording date. Corporate actions are announced ahead,
# so a window that starts in the past and ends in the future holds both the
# settled rows and the announced ones.
WINDOW = (dt.date(2026, 8, 1), dt.date(2026, 9, 30))

# One symbol per shape the mapper claims to handle, which is the only reason
# these five and not five large caps.
YAHOO_SYMBOLS = (
    "AAPL",  # the ordinary case: US equity, every quote field populated
    "RELIANCE.NS",  # an exchange suffix
    "531910.BO",  # a BSE scrip: numeric symbol, no longName
    "^GSPC",  # an index: no currentPrice, price only under regularMarketPrice
    "GVT&D.NS",  # the ampersand that the pre-Day-08b Symbol pattern rejected
)

# The field each exchange puts the free-text purpose in.
_RAW_FIELD = {Exchange.NSE: "subject", Exchange.BSE: "Purpose"}


class RecordingTransport(httpx.AsyncBaseTransport):
    """A real transport that keeps a copy of what it carried."""

    def __init__(self) -> None:
        self._inner = httpx.AsyncHTTPTransport()
        self.request: httpx.Request | None = None
        self.payload: Any = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        await response.aread()
        # Only the last exchange is kept. Both providers issue exactly one GET,
        # and a recorder that silently concatenated two would be a bug.
        self.request = request
        self.payload = json.loads(response.content)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


def write_fixture(relative: str, document: dict[str, Any]) -> Path:
    path = FIXTURES / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys and a trailing newline: a fixture gets re-recorded periodically,
    # and a diff that is only key reordering hides the diff that is a schema change.
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def trim(
    rows: list[dict[str, Any]], actions: tuple[CorporateAction, ...], exchange: Exchange
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Keep ROWS_PER_EVENT_TYPE rows per event type, in the order received.

    A row the provider rejected is always kept: an unmappable row is the one
    shape a hand-written test never thinks to include.
    """
    event_of = {action.raw: action.detail.type.value for action in actions}
    kept: list[dict[str, Any]] = []
    seen: Counter[str] = Counter()

    for row in rows:
        raw = row.get(_RAW_FIELD[exchange])
        event = event_of.get(raw.strip()) if isinstance(raw, str) else None
        if event is None:
            kept.append(row)  # rejected upstream, so it stays in full
            continue
        if seen[event] < ROWS_PER_EVENT_TYPE:
            seen[event] += 1
            kept.append(row)

    return kept, dict(sorted(seen.items()))


async def record_exchange(provider_type: type[NseProvider] | type[BseProvider]) -> Path:
    transport = RecordingTransport()
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        start, end = WINDOW
        actions = await provider_type(client).fetch(start, end)

    if transport.request is None:
        raise RuntimeError("the provider issued no request")
    rows = [row for row in transport.payload if isinstance(row, dict)]
    exchange = provider_type.exchange
    kept, distribution = trim(rows, actions, exchange)

    path = write_fixture(
        f"{exchange.value.lower()}_corporate_actions.json",
        {
            "exchange": exchange.value,
            "recorded_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "request": {
                "url": str(transport.request.url.copy_with(query=None)),
                "params": dict(transport.request.url.params),
            },
            "window": {"start": WINDOW[0].isoformat(), "end": WINDOW[1].isoformat()},
            "total_records": len(rows),
            "event_types": distribution,
            "records": kept,
        },
    )
    summary = ", ".join(f"{name} {count}" for name, count in distribution.items())
    print(f"{exchange.value}: {len(rows)} rows -> {len(kept)} kept ({summary})  {path.name}")
    return path


async def record_yahoo(symbol: str) -> Path:
    # The same seam the replay reads back. Recording anywhere else would let the
    # fixture and the test disagree about what "a Yahoo response" is.
    info, history = await YahooProvider()._fetch(symbol)

    bars = [
        {
            # iterrows() only promises Hashable for the index. yfinance always
            # returns a DatetimeIndex - the same cast mapper.py makes, for the
            # same reason.
            "date": cast(pd.Timestamp, timestamp).date().isoformat(),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        }
        for timestamp, row in history.iterrows()
    ]
    path = write_fixture(
        f"yahoo/{slug(symbol)}.json",
        {
            "symbol": symbol,
            "recorded_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "source": "yfinance Ticker(symbol).info + Ticker(symbol).history()",
            "info": info,
            "bars": bars,
        },
    )
    print(f"{symbol}: {len(info)} info keys, {len(bars)} bars  {path.name}")
    return path


def slug(symbol: str) -> str:
    """A filename that survives every filesystem. '^GSPC' and 'GVT&D.NS' do not."""
    return "".join(c if c.isalnum() else "_" for c in symbol).strip("_").lower()


async def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-record the replay fixtures.")
    parser.add_argument("--all", action="store_true", help="record every fixture")
    parser.add_argument("--nse", action="store_true", help="record the NSE calendar")
    parser.add_argument("--bse", action="store_true", help="record the BSE calendar")
    parser.add_argument("--yahoo", action="store_true", help="record every Yahoo symbol")
    args = parser.parse_args(argv)
    every = args.all or not (args.nse or args.bse or args.yahoo)

    if every or args.nse:
        await record_exchange(NseProvider)
    if every or args.bse:
        await record_exchange(BseProvider)
    if every or args.yahoo:
        for symbol in YAHOO_SYMBOLS:
            await record_yahoo(symbol)

    print(f"\nfixtures written under {FIXTURES}")
    print("now re-run the suite: uv run pytest -q")
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
