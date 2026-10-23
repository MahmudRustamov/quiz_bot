from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder, StorageKey
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from quizbot.db.models import FSMRecord


class PostgresStorage(BaseStorage):
    def __init__(self, sessions):
        self.sessions = sessions
        self.builder = DefaultKeyBuilder(with_bot_id=True, with_destiny=True)

    def key(self, key: StorageKey) -> str:
        return self.builder.build(key)

    async def _write(self, key, **values):
        async with self.sessions.begin() as session:
            stmt = insert(FSMRecord).values(key=self.key(key), **values)
            await session.execute(
                stmt.on_conflict_do_update(index_elements=[FSMRecord.key], set_=values)
            )

    async def set_state(self, key: StorageKey, state: State | str | None = None) -> None:
        await self._write(key, state=state.state if isinstance(state, State) else state)

    async def get_state(self, key: StorageKey) -> str | None:
        async with self.sessions() as session:
            record = await session.get(FSMRecord, self.key(key))
            return record.state if record else None

    async def set_data(self, key: StorageKey, data: dict) -> None:
        await self._write(key, data=dict(data))

    async def get_data(self, key: StorageKey) -> dict:
        async with self.sessions() as session:
            record = await session.get(FSMRecord, self.key(key))
            return dict(record.data) if record else {}

    async def update_data(self, key: StorageKey, data: dict) -> dict:
        async with self.sessions.begin() as session:
            stmt = insert(FSMRecord).values(key=self.key(key), data={})
            await session.execute(stmt.on_conflict_do_nothing(index_elements=[FSMRecord.key]))
            record = await session.scalar(
                select(FSMRecord).where(FSMRecord.key == self.key(key)).with_for_update()
            )
            merged = {**record.data, **data}
            record.data = merged
            return dict(merged)

    async def close(self) -> None:
        pass
