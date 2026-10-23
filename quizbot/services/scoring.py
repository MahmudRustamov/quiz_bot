"""Configurable scoring interface; calibration implementation remains intact."""

from typing import Protocol


class GradingStrategy(Protocol):
    async def result(self, actor: int, attempt_id: int) -> dict: ...


class RaschGradingService:
    def __init__(self, platform):
        self.platform = platform

    async def result(self, actor: int, attempt_id: int) -> dict:
        return await self.platform.rasch_result(actor, attempt_id)


class SimpleStrategy:
    def __init__(self, platform):
        self.platform = platform

    async def result(self, actor: int, attempt_id: int) -> dict:
        return await self.platform.simple_result(actor, attempt_id)


def grading_strategy(platform) -> GradingStrategy:
    return (
        SimpleStrategy(platform)
        if platform.settings.grading_strategy == "simple"
        else RaschGradingService(platform)
    )
