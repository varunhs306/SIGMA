"""A provider that answers from a dict.

This ships in `src/`, not `tests/`, on purpose. mypy checks `src/sigma` and
nothing else, so a fake living beside the tests is invisible to the type
checker and drifts away from the protocol silently - which is exactly the
failure the protocol was introduced to prevent.
"""

from sigma.domain import TickerSnapshot
from sigma.exceptions import ProviderError, SymbolNotFoundError


class FakeProvider:
    """A fake, not a mock: it has a real implementation, just an unrealistic one."""

    name = "fake"

    def __init__(
        self,
        snapshots: dict[str, TickerSnapshot] | None = None,
        *,
        fail_with: Exception | None = None,
    ) -> None:
        self._snapshots = dict(snapshots or {})
        self._fail_with = fail_with
        # Spy affordance. Tests assert on what was asked for, which a stub
        # returning a fixed value cannot answer.
        self.calls: list[str] = []

    async def get_snapshot(self, symbol: str) -> TickerSnapshot:
        self.calls.append(symbol)
        if self._fail_with is not None:
            raise self._fail_with
        try:
            return self._snapshots[symbol.upper()]
        except KeyError as e:
            # The same exception type the real adapter raises. A fake that
            # fails differently from production is a fake that hides bugs.
            raise SymbolNotFoundError(f"'{symbol}' is not in this FakeProvider") from e


class BrokenProvider:
    """Raises whatever it was built with. For the error paths only."""

    name = "broken"

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error or ProviderError("upstream is down")

    async def get_snapshot(self, symbol: str) -> TickerSnapshot:
        raise self._error
