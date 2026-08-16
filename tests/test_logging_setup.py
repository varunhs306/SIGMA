import json
import logging

import structlog

from sigma.logging.redaction import register_secret
from sigma.logging.setup import setup_logging
from tests.fakes import fake_telegram_token

TOKEN = fake_telegram_token()


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_exception_traceback_reaches_the_file(tmp_path, settings_factory):
    log_file = tmp_path / "sigma.log"
    setup_logging(settings_factory(log_file=log_file))
    log = structlog.get_logger("sigma.test")
    try:
        raise ValueError("boom")
    except Exception:
        log.exception("unhandled_exception")
    logging.shutdown()

    record = _read(log_file)[-1]
    assert record.get("exception") is not True, "format_exc_info missing from the chain"
    assert "ValueError: boom" in record["exception"]


def test_a_secret_inside_a_traceback_is_redacted(tmp_path, settings_factory):
    log_file = tmp_path / "sigma.log"
    setup_logging(settings_factory(log_file=log_file))
    register_secret(TOKEN)
    log = structlog.get_logger("sigma.test")
    try:
        raise ValueError(f"GET https://api.telegram.org/bot{TOKEN}/getUpdates")
    except Exception:
        log.exception("unhandled_exception")
    logging.shutdown()

    assert TOKEN not in log_file.read_text(encoding="utf-8")


def test_foreign_stdlib_records_are_redacted(tmp_path, settings_factory):
    log_file = tmp_path / "sigma.log"
    setup_logging(settings_factory(log_file=log_file))
    register_secret(TOKEN)
    logging.getLogger("httpx").warning(
        "HTTP Request: GET https://api.telegram.org/bot%s/getUpdates", TOKEN)
    logging.shutdown()

    text = log_file.read_text(encoding="utf-8")
    assert TOKEN not in text
    assert "***REDACTED***" in text


def test_every_line_is_valid_json_and_carries_level_and_logger(tmp_path, settings_factory):
    log_file = tmp_path / "sigma.log"
    setup_logging(settings_factory(log_file=log_file))
    structlog.get_logger("sigma.test").info("hello", n=1)
    logging.getLogger("httpx").warning("foreign line")
    logging.shutdown()

    for record in _read(log_file):
        assert "level" in record
        assert "logger" in record
        assert "timestamp" in record


def test_setup_is_idempotent(tmp_path, settings_factory):
    log_file = tmp_path / "sigma.log"
    settings = settings_factory(log_file=log_file)
    setup_logging(settings)
    setup_logging(settings)
    structlog.get_logger("sigma.test").info("once")
    logging.shutdown()

    assert len(_read(log_file)) == 1
