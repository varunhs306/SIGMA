import math

import pandas as pd

from sigma.providers.yahoo.mapper import present, to_bars, to_snapshot

# ^GSPC and 531910.BO both look like this: no currentPrice, a real price one key over.
INDEX_INFO = {"regularMarketPrice": 7691.76, "longName": "S&P 500"}


def _frame(rows):
    return pd.DataFrame(
        rows, index=pd.to_datetime([f"2026-07-{i + 1:02d}" for i in range(len(rows))])
    )


def test_the_price_falls_back_to_the_next_key():
    snapshot = to_snapshot("^GSPC", INDEX_INFO, None)
    assert snapshot.quote.price == 7691.76
    assert snapshot.profile.name == "S&P 500"


def test_yahoos_four_spellings_of_absence_all_become_none():
    info = {"sector": "", "beta": float("nan"), "marketCap": None}
    assert present(info, ("sector",)) is None
    assert present(info, ("beta",)) is None
    assert present(info, ("marketCap",)) is None
    assert present(info, ("industry",)) is None  # key not there at all


def test_bars_carry_python_floats_not_numpy_scalars():
    bars = to_bars(
        _frame([{"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10}]), "X"
    )
    assert type(bars[0].close) is float


def test_one_unusable_row_does_not_cost_the_others():
    frame = _frame(
        [
            {"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10},
            {"Open": math.nan, "High": math.nan, "Low": math.nan, "Close": math.nan, "Volume": 0},
            {"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.8, "Volume": 11},
        ]
    )
    bars = to_bars(frame, "X")
    assert len(bars) == 2
    assert [bar.close for bar in bars] == [1.5, 1.8]


def test_an_empty_history_is_no_bars_not_a_zero_change():
    snapshot = to_snapshot("^GSPC", INDEX_INFO, _frame([]))
    assert snapshot.bars == ()
    assert snapshot.price_change_30d is None


def test_the_mapper_needs_no_provider_to_run():
    # The point of splitting mapper from provider: this whole module tests the
    # translation with a literal dict and never constructs a YahooProvider.
    assert to_snapshot("AAPL", {"currentPrice": 1.0}, None).symbol == "AAPL"
