from sigma.bot import fmt_change


def test_absent_and_zero_are_distinguishable():
    assert fmt_change(None) == "N/A"
    assert fmt_change(0.0) == "0.00%"
