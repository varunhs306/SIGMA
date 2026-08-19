"""Free text in, typed event out.

Both exchanges describe a corporate action in a sentence written for a human.
BSE returned 192 distinct `Purpose` strings for a two-month window and NSE 162
distinct `subject` strings, for roughly six real events between them. This
module is the only place that reads those sentences.

The one rule that keeps it honest: **a string we do not recognise becomes
`UNKNOWN` with its raw text preserved, never a dropped row.** These strings
change without notice, and a parser that discards what it does not understand
converts a data problem into an invisible one.
"""

import re
from collections.abc import Callable

from pydantic import ValidationError

from sigma.domain import EventDetail, EventType
from sigma.logging import get_logger

logger = get_logger(__name__)

# Rs, Rs., Re and Re. all appear, and NSE picks between "Rs" and "Re" by whether
# the amount is above or below one. The currency word carries no information.
_RUPEES = r"(?:rs|re)\.?"
# Uncaptured, so it can be embedded either as a bare number or as a named group.
_NUM = r"\d[\d,]*(?:\.\d+)?"
_NUMBER = rf"({_NUM})"

_Rule = tuple[re.Pattern[str], Callable[[re.Match[str]], EventDetail]]


def _number(text: str) -> float:
    return float(text.replace(",", ""))


def _split(m: re.Match[str]) -> EventDetail:
    return EventDetail(
        type=EventType.SPLIT,
        face_value_from=_number(m.group(1)),
        face_value_to=_number(m.group(2)),
    )


def _bonus(m: re.Match[str]) -> EventDetail:
    return EventDetail(type=EventType.BONUS, ratio_new=int(m.group(1)), ratio_old=int(m.group(2)))


def _rights_with_ratio(m: re.Match[str]) -> EventDetail:
    return EventDetail(type=EventType.RIGHTS, ratio_new=int(m.group(1)), ratio_old=int(m.group(2)))


def _rights(m: re.Match[str]) -> EventDetail:
    return EventDetail(type=EventType.RIGHTS)


def _buyback(m: re.Match[str]) -> EventDetail:
    return EventDetail(type=EventType.BUYBACK)


def _amount_of(m: re.Match[str], event_type: EventType) -> EventDetail:
    try:
        raw_amount: str | None = m.group("amount")
    except IndexError:
        raw_amount = None
    return EventDetail(type=event_type, amount=_number(raw_amount) if raw_amount else None)


def _distribution(m: re.Match[str]) -> EventDetail:
    return _amount_of(m, EventType.DISTRIBUTION)


def _dividend(m: re.Match[str]) -> EventDetail:
    return _amount_of(m, EventType.DIVIDEND)


# Order is load-bearing. NSE writes an InvIT payout as
# "Distribution - Rs 1.94 Per Unit Consists Of ... As Dividend", so the
# distribution rule has to win before the dividend rule sees the word.
_RULES: tuple[_Rule, ...] = (
    # "Stock  Split From Rs.10/- to Rs.5/-" (BSE, note the double space) and
    # "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share" (NSE).
    (
        re.compile(
            rf"(?:stock\s+split|face\s+value\s+split).*?from\s+{_RUPEES}\s*{_NUMBER}"
            rf".*?to\s+{_RUPEES}\s*{_NUMBER}",
            re.IGNORECASE | re.DOTALL,
        ),
        _split,
    ),
    # "Bonus issue 1:1" (BSE), "Bonus 2:1" (NSE).
    (re.compile(r"bonus(?:\s+issue)?\s+(\d+)\s*:\s*(\d+)", re.IGNORECASE), _bonus),
    # "Rights 19:295 @ Premium Rs 205/-" (NSE).
    (re.compile(r"rights?\s+(\d+)\s*:\s*(\d+)", re.IGNORECASE), _rights_with_ratio),
    # "Right Issue of Equity Shares" (BSE) - a rights issue with no ratio quoted.
    (re.compile(r"rights?\s+issue", re.IGNORECASE), _rights),
    (re.compile(r"buy\s*back", re.IGNORECASE), _buyback),
    # "Income Distribution (InvIT)" (BSE, no amount) and
    # "Distribution - Rs 2.30 Per Unit Consists Of ..." (NSE).
    (
        re.compile(
            rf"distribution(?:\s*\([^)]*\))?(?:\s*(?:reits?|invits?))?"
            rf"(?:\s*[-\u2013]\s*{_RUPEES}\s*(?P<amount>{_NUM}))?",
            re.IGNORECASE,
        ),
        _distribution,
    ),
    # "Final Dividend - Rs. - 0.5000" (BSE), "Dividend - Re 0.25 Per Share" (NSE).
    # The optional leading dash is BSE's, and the amount is optional because a
    # dividend announced without a figure is still a dividend.
    (
        re.compile(
            rf"dividend(?:\s*[-\u2013]\s*{_RUPEES}\s*[-\u2013]?\s*(?P<amount>{_NUM}))?",
            re.IGNORECASE,
        ),
        _dividend,
    ),
)


def normalise(raw: str) -> EventDetail:
    """Parse one exchange purpose string. Never raises, never returns None."""
    text = " ".join(raw.split())
    if not text:
        return EventDetail(type=EventType.UNKNOWN)

    for pattern, build in _RULES:
        match = pattern.search(text)
        if match is None:
            continue
        try:
            return build(match)
        except (ValidationError, ValueError) as e:
            # A rule matched and produced something the domain rejects - a zero
            # dividend, a face value that grew. That is a parser bug or a new
            # upstream format, and both are better as UNKNOWN than as a lie.
            logger.warning("purpose_rejected_by_domain", raw=raw, rule=build.__name__, error=str(e))
            return EventDetail(type=EventType.UNKNOWN)

    logger.info("purpose_unrecognised", raw=raw)
    return EventDetail(type=EventType.UNKNOWN)
