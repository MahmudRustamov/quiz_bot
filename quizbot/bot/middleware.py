import asyncio
import logging
import time
from contextlib import suppress

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from quizbot.domain import DomainError

logger = logging.getLogger(__name__)


class ActiveUpdates(BaseMiddleware):
    """Drain or cancel handlers before closing sessions and worker processes."""

    def __init__(self):
        self.tasks = set()

    async def __call__(self, handler, event, data):
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            return await handler(event, data)
        finally:
            self.tasks.discard(task)

    async def shutdown(self, **kwargs):
        if self.tasks:
            _done, pending = await asyncio.wait(set(self.tasks), timeout=20)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)


class GuardMiddleware(BaseMiddleware):
    def __init__(self):
        self.buckets = {}

    async def __call__(self, handler, event, data):
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)
        message = event if isinstance(event, Message) else event.message
        if message is None or not hasattr(message, "chat") or message.chat.type != "private":
            if isinstance(event, CallbackQuery):
                await event.answer("Botdan shaxsiy suhbatda foydalaning.", show_alert=True)
            return
        user = event.from_user
        if user is None:
            return
        now = time.monotonic()
        previous, tokens = self.buckets.get(user.id, (now, 8.0))
        tokens = min(8.0, tokens + (now - previous) * 2)
        self.buckets[user.id] = (now, max(0, tokens - 1))
        if len(self.buckets) > 10000:
            self.buckets = {k: v for k, v in self.buckets.items() if now - v[0] < 60}
        if tokens < 1:
            await self.respond(event, "Biroz kutib, qayta urinib ko‘ring.")
            return
        try:
            return await handler(event, data)
        except DomainError as exc:
            await self.respond(event, str(exc))
        except (ValueError, ValidationError, UnicodeError, IndexError, KeyError):
            await self.respond(event, "Ma’lumot shakli noto‘g‘ri. Namuna va buyruqni tekshiring.")
        except SQLAlchemyError:
            # Do not log SQL parameters: they may include answers and personal information.
            logger.error("database_operation_failed", extra={"event_type": type(event).__name__})
            await self.respond(
                event, "Ma’lumotlar bazasiga ulanishda xatolik. Qayta urinib ko‘ring."
            )
        except TelegramAPIError:
            logger.warning("telegram_request_failed")
        except Exception as exc:
            logger.error("unexpected_handler_failure", extra={"exception_type": type(exc).__name__})
            await self.respond(
                event, "Kutilmagan xatolik. Qayta urinib ko‘ring yoki /cancel buyrug‘ini bosing."
            )

    @staticmethod
    async def respond(event, text):
        if isinstance(event, CallbackQuery):
            with suppress(TelegramAPIError):
                await event.answer()
            if event.message:
                await event.message.answer(text)
        else:
            await event.answer(text)
