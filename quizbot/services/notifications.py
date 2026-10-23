from datetime import timedelta

from sqlalchemy import select

from quizbot.db.models import Attempt, ResultNotification, User, utcnow
from quizbot.services.base import Service


class NotificationService(Service):
    async def pending_notifications(self):
        async with self.sessions() as session:
            return (
                await session.execute(
                    select(ResultNotification.id, ResultNotification.attempt_id, User.telegram_id)
                    .join(Attempt, Attempt.id == ResultNotification.attempt_id)
                    .join(User, User.id == Attempt.user_id)
                    .where(
                        ResultNotification.sent_at.is_(None),
                        ResultNotification.tries < 8,
                        ResultNotification.next_retry <= utcnow(),
                    )
                    .order_by(ResultNotification.id)
                    .limit(20)
                )
            ).all()

    async def mark_notification(self, notification_id: int, *, sent=False, blocked=False):
        async with self.sessions.begin() as session:
            record = await session.get(ResultNotification, notification_id, with_for_update=True)
            if record is not None:
                record.tries = 8 if blocked else record.tries + 1
                if sent:
                    record.sent_at = utcnow()
                record.next_retry = utcnow() + timedelta(seconds=min(3600, 15 * 2**record.tries))
