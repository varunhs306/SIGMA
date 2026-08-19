import datetime as dt

import pytest

from sigma.domain import EventDetail, EventType, Exchange
from sigma.store import EventStore
from tests.fakes import fake_action

EX = dt.date(2026, 8, 18)


class FakeClock:
    """A clock a test can move. Day 10 injects one into the backoff for the same reason."""

    def __init__(self) -> None:
        self.now = dt.datetime(2026, 8, 19, 6, 0, tzinfo=dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.now

    def tick(self, hours: int = 24) -> None:
        self.now += dt.timedelta(hours=hours)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def store(tmp_path, clock):
    return EventStore(tmp_path / "nested" / "sigma.db", now=clock)


def _seen(store, action):
    with store._connect() as conn:
        return conn.execute(
            "SELECT first_seen, last_seen FROM corporate_actions "
            "WHERE exchange = ? AND symbol = ? AND event_type = ? AND ex_date = ? AND raw = ?",
            (
                action.exchange.value,
                action.symbol,
                action.event_type.value,
                action.ex_date.isoformat(),
                action.raw,
            ),
        ).fetchone()


def test_the_store_creates_its_own_directory(tmp_path):
    # /data exists in the container; the subdirectory under it may not, and a
    # store that fails on first write fails after the bot is already up.
    path = tmp_path / "a" / "b" / "sigma.db"
    EventStore(path)
    assert path.exists()


def test_a_first_write_inserts(store):
    counts = store.upsert_many([fake_action()])
    assert (counts.inserted, counts.updated, counts.unchanged) == (1, 0, 0)
    assert store.count() == 1


def test_refetching_the_same_window_changes_nothing(store):
    actions = [fake_action(), fake_action(Exchange.BSE, "505283")]
    store.upsert_many(actions)

    counts = store.upsert_many(actions)

    # The property the whole design exists for: the daily job re-fetches a
    # window that is mostly unchanged, and running it twice is not two events.
    assert (counts.inserted, counts.updated, counts.unchanged) == (0, 0, 2)
    assert store.count() == 2


def test_a_changed_payload_updates_in_place(store):
    store.upsert_many([fake_action(ex_date=EX, record_date=dt.date(2026, 8, 18))])

    # Same announcement, corrected record date. The identity did not move, so
    # this is one event that changed rather than a second event.
    counts = store.upsert_many([fake_action(ex_date=EX, record_date=dt.date(2026, 8, 19))])

    assert (counts.inserted, counts.updated, counts.unchanged) == (0, 1, 0)
    assert store.count() == 1
    assert store.between(EX, EX)[0].record_date == dt.date(2026, 8, 19)


def test_two_dividends_on_one_day_are_two_events(store):
    # Linde India, ex-2026-08-06: a final dividend of Rs 4 and a special
    # dividend of Rs 8. Both are DIVIDEND on one date for one scrip, so a key
    # of (exchange, symbol, event_type, ex_date) stores one and loses the other.
    store.upsert_many(
        [
            fake_action(
                Exchange.BSE,
                "523457",
                detail=EventDetail(type=EventType.DIVIDEND, amount=4.0),
                ex_date=EX,
                raw="Final Dividend - Rs. - 4.0000",
            ),
            fake_action(
                Exchange.BSE,
                "523457",
                detail=EventDetail(type=EventType.DIVIDEND, amount=8.0),
                ex_date=EX,
                raw="Special Dividend - Rs. - 8.0000",
            ),
        ]
    )
    assert store.count() == 2


def test_two_interim_dividends_on_one_day_are_also_two_events(store):
    # Patanjali Foods, ex-2026-08-21. This is the pair that rules out a parsed
    # final/interim/special qualifier as the discriminator: both rows say
    # "Interim Dividend" and differ only in the amount.
    store.upsert_many(
        [
            fake_action(
                symbol="PATANJALI",
                detail=EventDetail(type=EventType.DIVIDEND, amount=0.80),
                ex_date=EX,
                raw="Interim Dividend - Re 0.80 Per Share",
            ),
            fake_action(
                symbol="PATANJALI",
                detail=EventDetail(type=EventType.DIVIDEND, amount=1.50),
                ex_date=EX,
                raw="Interim Dividend - Rs 1.50 Per Share",
            ),
        ]
    )
    assert store.count() == 2


def test_a_reworded_announcement_is_a_new_row(store):
    # The price of the key above, stated as a test rather than left as a
    # surprise: if an exchange edits the purpose text of an existing event, the
    # store holds both. Day 31 collapses them at alert time, where it has the
    # company and the ex-date to collapse on.
    store.upsert_many([fake_action(ex_date=EX, raw="Dividend - Rs 2 Per Share")])
    store.upsert_many([fake_action(ex_date=EX, raw="Dividend - Rs 2.00 Per Share")])
    assert store.count() == 2


def test_first_seen_is_when_we_first_saw_it_and_last_seen_moves(store, clock):
    action = fake_action()
    store.upsert_many([action])
    first_seen, first_last_seen = _seen(store, action)

    clock.tick()
    store.upsert_many([action])
    second_first_seen, second_last_seen = _seen(store, action)

    # Day 31 diffs today's fetch against the store to decide what is new, and
    # first_seen is the column that answers it. It must not move.
    assert second_first_seen == first_seen
    assert second_last_seen > first_last_seen


def test_a_dual_listed_company_is_stored_twice(store):
    # Same split, same ex-date, two exchanges, two rows. No ISIN join.
    store.upsert_many(
        [
            fake_action(Exchange.BSE, "505283", ex_date=EX),
            fake_action(Exchange.NSE, "KIRLPNU", ex_date=EX),
        ]
    )
    assert store.count() == 2


def test_two_events_for_one_company_in_one_window_both_survive(store):
    store.upsert_many(
        [
            fake_action(detail=EventDetail(type=EventType.DIVIDEND, amount=2.0)),
            fake_action(detail=EventDetail(type=EventType.BONUS, ratio_new=1, ratio_old=1)),
        ]
    )
    assert store.count() == 2


def test_a_stored_action_comes_back_as_the_object_that_went_in(store):
    action = fake_action(
        detail=EventDetail(type=EventType.SPLIT, face_value_from=2, face_value_to=1),
        ex_date=EX,
        raw="Stock  Split From Rs.2/- to Rs.1/-",
    )
    store.upsert_many([action])

    assert store.between(EX, EX) == (action,)


def test_the_window_query_is_inclusive_and_ordered(store):
    early = fake_action(ex_date=dt.date(2026, 8, 1))
    late = fake_action(ex_date=dt.date(2026, 9, 30))
    store.upsert_many([late, early])

    found = store.between(dt.date(2026, 8, 1), dt.date(2026, 9, 30))
    assert [a.ex_date for a in found] == [early.ex_date, late.ex_date]
    assert store.between(dt.date(2026, 8, 2), dt.date(2026, 9, 29)) == ()


def test_the_window_query_can_be_scoped_to_one_exchange(store):
    store.upsert_many([fake_action(Exchange.BSE, "505283", ex_date=EX), fake_action(ex_date=EX)])
    found = store.between(EX, EX, exchange=Exchange.BSE)
    assert [a.symbol for a in found] == ["505283"]


def test_an_unknown_event_round_trips_with_its_raw_text(store):
    action = fake_action(
        detail=EventDetail(type=EventType.UNKNOWN),
        ex_date=EX,
        raw="Resolution Plan -Suspension",
    )
    store.upsert_many([action])
    assert store.between(EX, EX)[0].raw == "Resolution Plan -Suspension"
