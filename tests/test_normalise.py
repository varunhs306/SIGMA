import pytest

from sigma.domain import EventType
from sigma.providers.corpactions.normalise import normalise

# Every string below was taken verbatim from a live response for the
# 2026-08-01 to 2026-09-30 window. Including the double space in the BSE split.
BSE_STRINGS = [
    ("Final Dividend - Rs. - 0.2500", EventType.DIVIDEND),
    ("Interim Dividend - Rs. - 4.0000", EventType.DIVIDEND),
    ("Dividend - Rs. - 1.5000", EventType.DIVIDEND),
    ("Special Dividend - Rs. - 1.0000", EventType.DIVIDEND),
    ("Bonus issue 1:1", EventType.BONUS),
    ("Bonus issue 1:2", EventType.BONUS),
    ("Stock  Split From Rs.10/- to Rs.5/-", EventType.SPLIT),
    ("Stock  Split From Rs.2/- to Rs.1/-", EventType.SPLIT),
    ("Buy Back of Shares ", EventType.BUYBACK),
    ("Right Issue of Equity Shares ", EventType.RIGHTS),
    ("Income Distribution (InvIT) ", EventType.DISTRIBUTION),
    ("Income Distribution REITs ", EventType.DISTRIBUTION),
    ("Reduction of Capital ", EventType.UNKNOWN),
    ("Scheme of Arrangement ", EventType.UNKNOWN),
    ("Resolution Plan -Suspension ", EventType.UNKNOWN),
]

NSE_STRINGS = [
    ("Dividend - Rs 2 Per Share", EventType.DIVIDEND),
    ("Dividend - Re 0.50 Per Share", EventType.DIVIDEND),
    ("Interim Dividend - Rs 1.50 Per Share", EventType.DIVIDEND),
    ("Bonus 2:1", EventType.BONUS),
    ("Buy Back", EventType.BUYBACK),
    ("Rights 19:295 @ Premium Rs 205/-", EventType.RIGHTS),
    (
        "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share",
        EventType.SPLIT,
    ),
    ("Distribution - Rs 1.1482 Per Unit As Interest", EventType.DISTRIBUTION),
    ("Interest Payment", EventType.UNKNOWN),
]


@pytest.mark.parametrize(("raw", "expected"), BSE_STRINGS + NSE_STRINGS)
def test_every_live_string_lands_on_the_right_type(raw, expected):
    assert normalise(raw).type is expected


def test_the_amount_survives_both_house_styles():
    # BSE pads to four decimals behind a second dash; NSE picks "Re" or "Rs"
    # by whether the figure is under one. Neither spelling means anything.
    assert normalise("Final Dividend - Rs. - 0.5000").amount == 0.5
    assert normalise("Dividend - Re 0.50 Per Share").amount == 0.5
    assert normalise("Dividend - Rs 60 Per Share").amount == 60.0


def test_a_split_is_a_face_value_change_and_a_factor():
    detail = normalise("Stock  Split From Rs.10/- to Rs.5/-")
    assert (detail.face_value_from, detail.face_value_to) == (10.0, 5.0)
    assert detail.split_factor == 2.0


def test_both_exchanges_describe_the_same_split_the_same_way():
    # BSE 505283 and NSE KIRLPNU, both ex-2026-08-18, one 2-for-1.
    bse = normalise("Stock  Split From Rs.2/- to Rs.1/-")
    nse = normalise("Face Value Split (Sub-Division) - From Rs 2/- Per Share To Re 1/- Per Share")
    assert bse == nse


def test_ratios_keep_both_halves():
    bonus = normalise("Bonus issue 1:2")
    assert (bonus.ratio_new, bonus.ratio_old) == (1, 2)
    rights = normalise("Rights 19:295 @ Premium Rs 205/-")
    assert (rights.ratio_new, rights.ratio_old) == (19, 295)


def test_a_distribution_is_not_read_as_a_dividend():
    # The trap: NSE writes an InvIT payout as a sentence containing the word
    # "Dividend", so rule order is what stops 0.40 being reported as the payout.
    raw = (
        "Distribution - Rs 2.30 Per Unit Consists Of Rs 1.70 Per Unit As Interest/ "
        "Re 0.20 Per Unit As Return Of Capital/ Re 0.40 Per Unit As Dividend"
    )
    detail = normalise(raw)
    assert detail.type is EventType.DISTRIBUTION
    assert detail.amount == 2.30


def test_an_unrecognised_string_is_unknown_and_never_an_exception():
    assert normalise("Something Nobody Has Written Yet").type is EventType.UNKNOWN
    assert normalise("").type is EventType.UNKNOWN
    assert normalise("   ").type is EventType.UNKNOWN


def test_a_match_the_domain_rejects_degrades_to_unknown():
    # A zero dividend is a parse failure, not a zero dividend. The rule matches,
    # EventDetail refuses it, and the result is UNKNOWN rather than a lie.
    assert normalise("Final Dividend - Rs. - 0.0000").type is EventType.UNKNOWN
    # A "split" that raises face value is a consolidation, which we do not claim
    # to parse, so it does not get to masquerade as a split.
    assert normalise("Stock Split From Rs.1/- to Rs.10/-").type is EventType.UNKNOWN
