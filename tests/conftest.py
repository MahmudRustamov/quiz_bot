import os

import pytest
from sqlalchemy import text

from quizbot.config import Settings
from quizbot.db import database
from quizbot.services import Platform


@pytest.fixture
async def platform():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable migrated PostgreSQL database")
    if "test" not in url.rsplit("/", 1)[-1]:
        raise RuntimeError("Integration tests require a database with 'test' in its name")
    engine, sessions = database(url)
    async with engine.begin() as connection:
        # These tests own the entire disposable database; never point at production.
        await connection.execute(
            text(
                "TRUNCATE TABLE result_notifications, standardized_scores, student_ability_estimates, item_parameters, grading_results, student_responses, attempts, questions, exams, grading_policies, calibration_runs, users, audit_logs, fsm_records RESTART IDENTITY CASCADE"
            )
        )
    yield Platform(
        sessions,
        Settings(
            _env_file=None, admin_ids=[999], calibration_min_students=30, grading_strategy="rasch"
        ),
    )
    await engine.dispose()


@pytest.fixture
def simple_platform(platform, tmp_path):
    return Platform(
        platform.sessions,
        platform.settings.model_copy(
            update={
                "grading_strategy": "simple",
                "simple_release_policy": "immediate",
                "results_dir": tmp_path / "results",
            }
        ),
    )
