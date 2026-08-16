import structlog

from sigma.logging.context import bind_run, new_run


def test_run_id_is_bound_and_returned():
    run_id = new_run(ticker="AAPL")
    bound = structlog.contextvars.get_contextvars()
    assert bound["run_id"] == run_id
    assert bound["ticker"] == "AAPL"


def test_each_run_gets_a_distinct_id():
    assert new_run() != new_run()


def test_new_run_clears_previous_fields():
    new_run(ticker="AAPL", command="price")
    new_run(command="analyze")
    assert "ticker" not in structlog.contextvars.get_contextvars()


def test_bind_run_adds_without_resetting_the_run_id():
    run_id = new_run(command="price")
    bind_run(ticker="TCS.NS")
    bound = structlog.contextvars.get_contextvars()
    assert bound["run_id"] == run_id
    assert bound["ticker"] == "TCS.NS"
