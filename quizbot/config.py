from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    bot_token: SecretStr = SecretStr("")
    database_url: SecretStr = SecretStr("postgresql+asyncpg://quiz:change-me@localhost:5432/quiz")
    admin_ids: list[int] = Field(default_factory=list)
    log_level: str = "INFO"
    grading_strategy: Literal["simple", "rasch"] = "simple"
    simple_release_policy: Literal["immediate", "manual"] = "immediate"
    report_timezone: str = "Asia/Tashkent"
    results_dir: Path = Path("results")
    calibration_min_students: int = Field(default=100, ge=30)
    calibration_timeout_seconds: int = Field(default=180, ge=10, le=3600)

    @field_validator("report_timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("REPORT_TIMEZONE must name an IANA timezone") from exc
        return value

    @field_validator("admin_ids")
    @classmethod
    def valid_admins(cls, value: list[int]) -> list[int]:
        if any(i <= 0 for i in value):
            raise ValueError("ADMIN_IDS must contain positive Telegram user IDs")
        return sorted(set(value))
