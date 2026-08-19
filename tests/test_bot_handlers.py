import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Chat, Message, MessageEntity, Update, User

from sigma.bot import Handlers, fmt_change
from sigma.exceptions import ProviderRateLimited
from sigma.providers import BrokenProvider, FakeProvider
from tests.fakes import fake_snapshot


def _command_message(**kwargs) -> Message:
    return Message(
        message_id=1,
        date=dt.datetime.now(dt.UTC),
        chat=Chat(id=1, type="group", title="t"),
        text="/price AAPL",
        entities=[MessageEntity(type="bot_command", offset=0, length=6)],
        **kwargs,
    )


def _ctx(args=("AAPL",)):
    ctx = MagicMock()
    ctx.args = list(args)
    return ctx


async def _analyse(snapshot) -> str:
    return f"analysis of {snapshot.symbol}"


def _handlers(provider=None) -> Handlers:
    # No monkeypatching. The collaborators are constructor arguments, so a test
    # builds the object it wants instead of reaching into another module.
    return Handlers(provider=provider or FakeProvider({"AAPL": fake_snapshot()}), analyse=_analyse)


@pytest.fixture
def replies(monkeypatch):
    # Message.reply_text is still patched: it is Telegram's network call, not
    # ours, and PTB gives no seam for it.
    sent = AsyncMock()
    monkeypatch.setattr(Message, "reply_text", sent)
    return sent


def test_absent_and_zero_are_distinguishable():
    assert fmt_change(None) == "N/A"
    assert fmt_change(0.0) == "0.00%"


async def test_edited_command_does_not_crash(replies):
    user = User(id=7, first_name="u", is_bot=False)
    update = Update(update_id=1, edited_message=_command_message(from_user=user))

    assert update.message is None
    assert update.effective_message is not None

    await _handlers().price(update, _ctx())
    assert replies.await_count > 0


async def test_channel_post_without_a_user_does_not_crash(replies):
    update = Update(update_id=2, channel_post=_command_message())

    assert update.effective_user is None
    assert update.effective_message is not None

    await _handlers().price(update, _ctx())
    assert replies.await_count > 0


async def test_update_with_no_message_returns_quietly():
    await _handlers().price(Update(update_id=3), _ctx())


async def test_the_handler_asks_the_provider_for_what_the_user_typed(replies):
    provider = FakeProvider({"AAPL": fake_snapshot()})
    update = Update(update_id=4, message=_command_message())

    await Handlers(provider=provider, analyse=_analyse).price(update, _ctx(["aapl"]))

    # Upper-cased by the handler before it ever reaches a provider. The fake
    # records the call, which a stub returning a fixed value could not.
    assert provider.calls == ["AAPL"]


async def test_a_provider_failure_reaches_the_user_as_its_own_message(replies):
    provider = BrokenProvider(ProviderRateLimited("429"))
    update = Update(update_id=5, message=_command_message())

    await Handlers(provider=provider, analyse=_analyse).price(update, _ctx())

    assert "busy" in replies.await_args_list[-1].args[0].lower()


async def test_analyze_passes_the_snapshot_to_the_analyser(replies):
    update = Update(update_id=6, message=_command_message())

    await _handlers().analyze(update, _ctx())

    assert "analysis of AAPL" in replies.await_args_list[-1].args[0]
