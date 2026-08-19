"""Corporate actions: the things that happen *to* a share.

A `TickerSnapshot` answers "what is this company worth right now". These models
answer "what is about to happen to it", and they arrive from a different kind of
source - one bulk query per exchange rather than one request per company.
"""

import datetime as dt
from enum import StrEnum
from typing import Self

from pydantic import computed_field, model_validator

from sigma.domain.models import DomainModel, Name, Symbol


class Exchange(StrEnum):
    """An exchange, and the yfinance suffix that addresses it.

    A symbol without an exchange is not an identifier. `EMKAY` and `531910` are
    both real and both meaningless until you know which venue said so.
    """

    NSE = "NSE"
    BSE = "BSE"

    @property
    def suffix(self) -> str:
        return {Exchange.NSE: ".NS", Exchange.BSE: ".BO"}[self]


class EventType(StrEnum):
    """Six real events and an escape hatch.

    UNKNOWN is not a failure mode, it is the honest answer for 'Scheme of
    Arrangement' and the other long tail. The raw text always survives beside it.
    """

    DIVIDEND = "DIVIDEND"
    BONUS = "BONUS"
    SPLIT = "SPLIT"
    RIGHTS = "RIGHTS"
    BUYBACK = "BUYBACK"
    DISTRIBUTION = "DISTRIBUTION"
    UNKNOWN = "UNKNOWN"


class EventDetail(DomainModel):
    """The typed part of a free-text purpose string.

    Every field is optional because every field is genuinely absent for some
    event type: a buyback has no amount, a dividend has no ratio.
    """

    type: EventType
    # Per share for DIVIDEND, per unit for DISTRIBUTION. Never negative; a
    # dividend of zero is a parse failure, not a zero dividend.
    amount: float | None = None
    # BONUS 2:1 is two new shares for one held. RIGHTS 3:5 is three offered per
    # five held. Same shape, different meaning, so the type carries the meaning.
    ratio_new: int | None = None
    ratio_old: int | None = None
    # SPLIT is quoted as a face value change: Rs.10 -> Rs.1 is a ten-for-one.
    face_value_from: float | None = None
    face_value_to: float | None = None

    @model_validator(mode="after")
    def _amount_is_positive(self) -> Self:
        if self.amount is not None and self.amount <= 0:
            raise ValueError(f"amount {self.amount} is not positive")
        return self

    @model_validator(mode="after")
    def _ratio_is_a_pair(self) -> Self:
        if (self.ratio_new is None) != (self.ratio_old is None):
            raise ValueError("a ratio needs both halves or neither")
        if self.ratio_new is not None and (self.ratio_new <= 0 or (self.ratio_old or 0) <= 0):
            raise ValueError(f"ratio {self.ratio_new}:{self.ratio_old} has a non-positive side")
        return self

    @model_validator(mode="after")
    def _face_values_are_a_shrinking_pair(self) -> Self:
        old, new = self.face_value_from, self.face_value_to
        if (old is None) != (new is None):
            raise ValueError("a face value change needs both halves or neither")
        if old is not None and new is not None:
            if old <= 0 or new <= 0:
                raise ValueError(f"face value {old} -> {new} has a non-positive side")
            # A sub-division only ever reduces face value. The reverse is a
            # consolidation, which these feeds spell differently and we do not
            # claim to parse.
            if new >= old:
                raise ValueError(f"face value {old} -> {new} is not a sub-division")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def split_factor(self) -> float | None:
        """10 -> 1 is a 10x split. None when this is not a split we could size."""
        if self.face_value_from is None or self.face_value_to is None:
            return None
        return round(self.face_value_from / self.face_value_to, 4)


class CorporateAction(DomainModel):
    """One event, on one exchange, for one company.

    `symbol` is exchange-native and `ticker` is what yfinance answers to. They
    are two different identifiers for the same company and conflating them is
    the bug that returns an empty result set instead of an error.
    """

    exchange: Exchange
    symbol: str
    ticker: Symbol
    company: Name | None = None
    # NSE supplies it, BSE does not. Day 08b declines to fetch a second source
    # to fill the gap - see the module docstring of providers/corpactions/base.py.
    isin: str | None = None
    detail: EventDetail
    ex_date: dt.date
    record_date: dt.date | None = None
    # The string the exchange actually sent. Never dropped, whatever we made of it.
    raw: str

    @model_validator(mode="after")
    def _ticker_belongs_to_the_exchange(self) -> Self:
        if not self.ticker.endswith(self.exchange.suffix):
            raise ValueError(f"ticker {self.ticker} is not a {self.exchange} ticker")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def event_type(self) -> EventType:
        return self.detail.type

    @property
    def key(self) -> tuple[str, str, str, dt.date, str]:
        """The identity of an event, and the store's primary key.

        Deliberately not ISIN-based and deliberately not cross-exchange: a
        dual-listed company legitimately has two of these, sometimes with
        different dates.

        `raw` is in the key because nothing else separates two real events.
        Linde India declares a final dividend of Rs 4 and a special dividend of
        Rs 8 on the same ex-date, and Patanjali Foods declares two *interim*
        dividends on one - so neither the type, nor a parsed final/interim/
        special qualifier, nor the amount is enough. Measured over one two-month
        window: keying without it silently collapses 8 of 967 events.
        """
        return (
            self.exchange.value,
            self.symbol,
            self.detail.type.value,
            self.ex_date,
            self.raw,
        )
