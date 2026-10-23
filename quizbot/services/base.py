from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quizbot.config import Settings
from quizbot.db.models import Attempt, AuditLog, Exam, User
from quizbot.domain import DomainError, Forbidden


class Service:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings):
        self.sessions = sessions
        self.settings = settings

    def admin(self, actor: int) -> None:
        if actor not in self.settings.admin_ids:
            raise Forbidden()

    @staticmethod
    def audit(session, actor: int, action: str, **details):
        session.add(AuditLog(actor_id=actor, action=action, details=details))

    async def register(
        self,
        telegram_id: int,
        full_name: str | None = None,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> User:
        if full_name is not None and first_name is None and last_name is None:
            pieces = full_name.split(maxsplit=1)
            first_name = pieces[0] if pieces else ""
            last_name = pieces[1] if len(pieces) == 2 else ""
        first_name, last_name = (
            self.validate_name(first_name or ""),
            self.validate_name(last_name or ""),
        )
        name = f"{first_name} {last_name}"
        async with self.sessions.begin() as session:
            # Upsert makes simultaneous /start registrations safe.
            from sqlalchemy.dialects.postgresql import insert

            values = {"full_name": name, "first_name": first_name, "last_name": last_name}
            statement = insert(User).values(telegram_id=telegram_id, **values)
            statement = statement.on_conflict_do_update(
                index_elements=[User.telegram_id], set_=values
            ).returning(User)
            return (await session.execute(statement)).scalar_one()

    @staticmethod
    def validate_name(value: str) -> str:
        value = " ".join(value.split())
        if not 1 <= len(value) <= 74 or value.startswith("/"):
            raise DomainError("Ism va familiyaning har biri 1–74 belgidan iborat bo‘lsin.")
        return value

    async def profile(self, actor: int) -> User | None:
        async with self.sessions() as session:
            return await session.scalar(select(User).where(User.telegram_id == actor))

    async def students(self, actor: int, page: int = 0) -> list[User]:
        self.admin(actor)
        async with self.sessions() as session:
            return list(
                await session.scalars(
                    select(User).order_by(User.id).offset(max(page, 0) * 10).limit(10)
                )
            )

    @staticmethod
    async def locked_exam(session: AsyncSession, exam_id: int) -> Exam:
        exam = await session.scalar(select(Exam).where(Exam.id == exam_id).with_for_update())
        if exam is None:
            raise DomainError("Test topilmadi.")
        return exam

    async def owned_attempt(self, session, attempt_id: int, actor: int, *, lock: bool = False):
        # All mutations lock exam before attempt, consistently with administration.
        query = (
            select(Attempt).join(User).where(Attempt.id == attempt_id, User.telegram_id == actor)
        )
        attempt = await session.scalar(query)
        if attempt is None:
            raise Forbidden()
        if lock:
            await self.locked_exam(session, attempt.exam_id)
            attempt = await session.scalar(
                query.with_for_update(of=Attempt).execution_options(populate_existing=True)
            )
        return attempt
