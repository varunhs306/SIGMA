"""What the engine is allowed to know about a data source.

The direction of the arrow is the whole point. `bot.py` imports this module;
this module imports `sigma.domain`; neither imports yfinance. A provider is
whatever satisfies the shape below, and nothing above this line can tell which
one it got.
"""

from typing import Protocol, runtime_checkable

from sigma.domain import TickerSnapshot


@runtime_checkable
class MarketDataProvider(Protocol):
    """One company, everything we know about it right now.

    Implementations raise `SigmaError` subclasses and nothing else: a caller
    that has to know `yfinance.exceptions` exists is a caller this protocol
    failed to protect.
    """

    # A plain annotation, not a method: an implementation satisfies it with
    # `name = "yahoo"` at class level. It exists for log binding and for the
    # provenance stamp Day 14 adds.
    name: str

    async def get_snapshot(self, symbol: str) -> TickerSnapshot:
        """Raise SymbolNotFoundError if the symbol is unknown, never return None."""
        ...
