from datetime import UTC, datetime

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from quizbot.__main__ import dispatcher
from quizbot.importing import ExamSpec

pytestmark = pytest.mark.postgres


class FakeTelegram(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        return Message(
            message_id=len(self.calls),
            date=datetime.now(UTC),
            chat=Chat(id=int(method.chat_id), type="private"),
            text=getattr(method, "text", None),
        )

    async def stream_content(self, *args, **kwargs):
        yield b""


async def test_real_dispatch_registration_navigation_and_admin_guard(platform):
    fake = FakeTelegram()
    bot = Bot("123456:TEST_TOKEN_FOR_LOCAL_TESTS", session=fake)
    dp = dispatcher(platform.sessions)
    sequence = 0

    async def send(actor, text=None, callback=None):
        nonlocal sequence
        sequence += 1
        user = User(id=actor, is_bot=False, first_name="Test")
        message = Message(
            message_id=sequence,
            date=datetime.now(UTC),
            chat=Chat(id=actor, type="private"),
            from_user=user,
            text=text or "test",
        )
        update = (
            Update(update_id=sequence, message=message)
            if callback is None
            else Update(
                update_id=sequence,
                callback_query=CallbackQuery(
                    id=str(sequence),
                    from_user=user,
                    chat_instance="local",
                    message=message,
                    data=callback,
                ),
            )
        )
        await dp.feed_update(bot, update, platform=platform)

    await send(123, "/start")
    assert "ismingizni" in fake.calls[-1].text
    await send(123, "Ali")
    assert "Familiyangizni" in fake.calls[-1].text
    await send(123, "Vali")
    assert (await platform.profile(123)).full_name == "Ali Vali"
    exam = await platform.import_exam(
        999,
        ExamSpec(
            title="Dispatch test",
            materials=[
                {
                    "key": "passage",
                    "title": "Reading passage",
                    "text": "Synthetic reading passage. " * 200,
                }
            ],
            questions=[
                {
                    "number": 1,
                    "kind": "written",
                    "statement": "Synthetic prompt",
                    "material_keys": ["passage"],
                    "parts": [{"accepted": ["x"]}],
                }
            ],
        ),
    )
    await platform.set_published(999, exam.id, True)
    await send(123, callback=f"exam:{exam.id}")
    assert "Synthetic prompt" in fake.calls[-1].text

    def reading_count():
        return sum((getattr(call, "text", None) or "").startswith("📖") for call in fake.calls)

    assert reading_count() == 1
    await send(123, "x")
    assert reading_count() == 1
    attempt = (await platform.history(123))[0]["id"]
    await send(123, callback=f"material:{attempt}:0")
    assert reading_count() == 2
    await send(123, "📊 Natijalarim")
    assert "Natijalaringiz" in fake.calls[-1].text
    await send(123, callback=f"act:close:{exam.id}")
    assert "ruxsatingiz yo‘q" in fake.calls[-1].text
    await send(999, "/create")
    await send(999, "/cancel")
    assert "Menyu" in fake.calls[-1].text
    await send(888, "/release 1 raw")
    assert "ruxsatingiz yo‘q" in fake.calls[-1].text
    await dp.storage.close()
    await bot.session.close()
