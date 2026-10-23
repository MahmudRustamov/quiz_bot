import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.storage.memory import SimpleEventIsolation
from sqlalchemy import text

from quizbot.bot import admin, student
from quizbot.bot.keyboards import inline
from quizbot.bot.middleware import ActiveUpdates, GuardMiddleware
from quizbot.bot.storage import PostgresStorage
from quizbot.config import Settings
from quizbot.db import database
from quizbot.logging import configure_logging
from quizbot.services import Platform

logger = logging.getLogger(__name__)


async def sweeper(platform, bot):
    while True:
        try:
            await platform.expire_attempts()
            for notification_id, attempt_id, telegram_id in await platform.pending_notifications():
                try:
                    await bot.send_message(
                        telegram_id,
                        "Natijalaringiz e’lon qilindi. Ko‘rish uchun tugmani bosing.",
                        reply_markup=inline([[("Natijani ko‘rish", f"result:{attempt_id}")]]),
                    )
                    await platform.mark_notification(notification_id, sent=True)
                except TelegramForbiddenError:
                    await platform.mark_notification(notification_id, blocked=True)
                except TelegramRetryAfter as exc:
                    await platform.mark_notification(notification_id)
                    await asyncio.sleep(min(exc.retry_after, 30))
                    break
                except TelegramAPIError:
                    await platform.mark_notification(notification_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("deadline_sweeper_failed")
        await asyncio.sleep(10)


def dispatcher(sessions):
    dp = Dispatcher(storage=PostgresStorage(sessions), events_isolation=SimpleEventIsolation())
    active = ActiveUpdates()
    dp.update.outer_middleware(active)
    dp.shutdown.register(active.shutdown)
    guard = GuardMiddleware()
    dp.message.outer_middleware(guard)
    dp.callback_query.outer_middleware(guard)
    dp.include_routers(admin.router, student.router)

    async def unhandled_error(event):
        # Includes failures in FSM middleware, outside the per-message guard.
        logger.error(
            "update_processing_failed", extra={"exception_type": type(event.exception).__name__}
        )
        update = event.update
        target = update.callback_query or update.message
        if target:
            with contextlib.suppress(TelegramAPIError):
                await GuardMiddleware.respond(
                    target, "Xizmatda vaqtinchalik xatolik. Qayta urinib ko‘ring."
                )
        return True

    dp.errors.register(unhandled_error)
    return dp


async def run():
    settings = Settings()
    configure_logging(settings.log_level)
    if (
        not settings.bot_token.get_secret_value()
        or settings.bot_token.get_secret_value() == "replace-with-botfather-token"
    ):
        raise SystemExit("BOT_TOKEN ni .env faylida sozlang.")
    engine, sessions = database(settings.database_url.get_secret_value())
    bot = Bot(settings.bot_token.get_secret_value(), session=AiohttpSession(timeout=35))
    task = None
    try:
        # One long-polling process per database. Session-level lock survives commits.
        async with engine.connect() as connection:
            acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(610442001)"))
            if not acquired:
                raise SystemExit("Ushbu bazada botning boshqa nusxasi ishlamoqda.")
            await connection.commit()
            platform = Platform(sessions, settings)
            if settings.grading_strategy == "rasch":
                await platform.recover_interrupted_runs()
            task = asyncio.create_task(sweeper(platform, bot))
            dp = dispatcher(sessions)
            try:
                await dp.start_polling(
                    bot,
                    platform=platform,
                    tasks_concurrency_limit=32,
                    allowed_updates=dp.resolve_used_update_types(),
                )
            finally:
                await connection.execute(text("SELECT pg_advisory_unlock(610442001)"))
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await bot.session.close()
        await engine.dispose()


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
