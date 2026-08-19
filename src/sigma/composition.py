"""The composition root: the one module that knows which implementations are real.

Everything below this line depends on protocols. This module depends on
concretions, imports the vendor SDKs, and owns the lifetimes that go with them.
Move a single import out of here and the dependency inversion is gone.

It is deliberately the last thing built and the first thing a new reader
should open: the object graph of the whole application is 40 lines.
"""

import datetime as dt
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from sigma.analyzer import analyze_ticker
from sigma.bot import Handlers
from sigma.config import get_settings
from sigma.providers import MarketDataProvider
from sigma.providers.corpactions import BseProvider, CorporateActionProvider, NseProvider
from sigma.providers.yahoo import YahooProvider
from sigma.store import EventStore

# The window a scheduled refresh asks for. Wide enough that a missed day costs
# nothing, because the upsert makes the overlap free.
DEFAULT_WINDOW_DAYS = 60


def build_market_data_provider() -> MarketDataProvider:
    return YahooProvider()


def build_handlers() -> Handlers:
    return Handlers(provider=build_market_data_provider(), analyse=analyze_ticker)


def build_event_store() -> EventStore:
    # Under data_dir, which is /data in the container. A relative path here
    # would put the database in whatever directory the process started in.
    return EventStore(get_settings().data_dir / "sigma.db")


@asynccontextmanager
async def corpaction_providers() -> AsyncIterator[tuple[CorporateActionProvider, ...]]:
    """Both exchanges, sharing one HTTP client, closed on the way out.

    An async context manager rather than a factory because a client is a
    resource: constructing one and never closing it leaks connections, and
    deciding *when* it closes is a composition concern, not a provider one.
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        yield (NseProvider(client), BseProvider(client))


def default_window(today: dt.date | None = None) -> tuple[dt.date, dt.date]:
    """Today to today + DEFAULT_WINDOW_DAYS. Corporate actions are announced ahead."""
    start = today or dt.date.today()
    return start, start + dt.timedelta(days=DEFAULT_WINDOW_DAYS)
