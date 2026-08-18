"""The vocabulary every other module speaks.

Nothing here imports a provider, the config or a logger. A model is a *parse
result*: if one of these objects exists, its invariants already hold, so no
caller downstream has to re-check them.
"""

import datetime as dt
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    model_validator,
)


def _normalise_symbol(value: Any) -> Any:
    # BeforeValidator, not StringConstraints(to_upper=True): to_upper runs AFTER
    # the pattern test, so "aapl" would be rejected before it was ever upcased.
    return value.strip().upper() if isinstance(value, str) else value


# 20 characters, not 10: "RELIANCE.NS" is 11 and the old fetcher regex rejected it.
Symbol = Annotated[
    str,
    BeforeValidator(_normalise_symbol),
    StringConstraints(pattern=r"^[A-Z0-9.\-^]{1,20}$"),
]

# allow_inf_nan=False is the load-bearing part. Pydantic accepts nan and inf as
# ordinary floats by default, and pandas produces both.
Price = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Ratio = Annotated[float, Field(allow_inf_nan=False)]
Cap = Annotated[int, Field(gt=0)]
Shares = Annotated[int, Field(ge=0)]
Percent = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DomainModel(BaseModel):
    # frozen: a snapshot is a fact about a moment, and facts do not get edited.
    # extra: a mistyped keyword is a failure here, not a field silently dropped.
    model_config = ConfigDict(frozen=True, extra="forbid")


class PriceBar(DomainModel):
    """One trading day. The unit price history is made of."""

    date: dt.date
    open: Price
    high: Price
    low: Price
    close: Price
    volume: Shares

    @model_validator(mode="after")
    def _range_is_coherent(self) -> Self:
        if self.high < self.low:
            raise ValueError(f"high {self.high} is below low {self.low}")
        if not self.low <= self.open <= self.high:
            raise ValueError(f"open {self.open} sits outside [{self.low}, {self.high}]")
        if not self.low <= self.close <= self.high:
            raise ValueError(f"close {self.close} sits outside [{self.low}, {self.high}]")
        return self


class CompanyProfile(DomainModel):
    """Who the company is. Everything but the symbol may be genuinely unknown."""

    symbol: Symbol
    name: Name | None = None
    sector: Name | None = None
    industry: Name | None = None


class Quote(DomainModel):
    """A point-in-time market snapshot. If a Quote exists, it has a price."""

    symbol: Symbol
    price: Price
    market_cap: Cap | None = None
    trailing_pe: Ratio | None = None
    forward_pe: Ratio | None = None
    price_to_book: Ratio | None = None
    week_52_high: Price | None = None
    week_52_low: Price | None = None
    volume: Shares | None = None
    avg_volume: Shares | None = None
    beta: Ratio | None = None
    dividend_yield: Percent | None = None

    @model_validator(mode="after")
    def _52_week_range_is_ordered(self) -> Self:
        low, high = self.week_52_low, self.week_52_high
        if low is not None and high is not None and high < low:
            raise ValueError(f"52-week high {high} is below low {low}")
        return self


class TickerSnapshot(DomainModel):
    """Everything one /price or /analyze call knows about one company.

    This is the object that crosses a module boundary; the three models above
    are its parts.
    """

    profile: CompanyProfile
    quote: Quote
    # tuple, not list: a frozen model with a mutable field is not frozen.
    bars: tuple[PriceBar, ...] = ()

    @property
    def symbol(self) -> str:
        return self.quote.symbol

    @model_validator(mode="after")
    def _one_company(self) -> Self:
        if self.profile.symbol != self.quote.symbol:
            raise ValueError(f"profile is {self.profile.symbol}, quote is {self.quote.symbol}")
        return self

    @model_validator(mode="after")
    def _bars_are_chronological(self) -> Self:
        # price_change_30d reads bars[0] and bars[-1]. That is only a change
        # over time if the order is the one it assumes.
        dates = [bar.date for bar in self.bars]
        if dates != sorted(dates):
            raise ValueError("bars are not in chronological order")
        if len(set(dates)) != len(dates):
            raise ValueError("bars contain duplicate dates")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def price_change_30d(self) -> float | None:
        """None when unknowable. Two bars are the minimum that can express a change."""
        if len(self.bars) < 2:
            return None
        first, last = self.bars[0].close, self.bars[-1].close
        return round((last - first) / first * 100, 2)
