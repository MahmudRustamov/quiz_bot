import asyncio
import io
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
from aiogram.fsm.storage.base import StorageKey
from sqlalchemy import func, select, update

from quizbot.bot.storage import PostgresStorage
from quizbot.db.models import (
    Attempt,
    CalibrationRun,
    GradingResult,
    Question,
    QuestionPart,
    StudentResponse,
    User,
    utcnow,
)
from quizbot.domain import DomainError, Forbidden
from quizbot.importing import ExamSpec, PolicySpec, QuestionSpec
from quizbot.psychometrics.models import rasch_probability

pytestmark = pytest.mark.postgres


def spec(*, written=False, review=False, n=4):
    return ExamSpec(
        title="Sinov",
        duration_minutes=60,
        policy={"min_students": 30},
        questions=[
            QuestionSpec(
                number=i + 1,
                kind="written" if written else "mcq",
                statement=f"Synthetic test question {i + 1}",
                options={} if written else {"A": "First", "B": "Second"},
                parts=[{"accepted": ["A"], "manual_review": review}],
            )
            for i in range(n)
        ],
    )


async def setup_exam(platform, **kwargs):
    exam = await platform.import_exam(999, spec(**kwargs))
    await platform.set_published(999, exam.id, True)
    await platform.register(123, "Ali Vali")
    return exam, await platform.start_attempt(123, exam.id)


async def test_duplicate_start_and_submission(platform):
    exam = await platform.import_exam(999, spec())
    await platform.set_published(999, exam.id, True)
    await asyncio.gather(platform.register(123, "Ali Vali"), platform.register(123, "Ali Vali"))
    a, b = await asyncio.gather(
        platform.start_attempt(123, exam.id), platform.start_attempt(123, exam.id)
    )
    assert a.id == b.id
    view = await platform.question_view(123, a.id)
    await platform.save_answer(123, a.id, view["part_id"], "A")
    first, second = await asyncio.gather(
        platform.submit_attempt(123, a.id), platform.submit_attempt(123, a.id)
    )
    assert first.raw_score == second.raw_score == 1
    async with platform.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(GradingResult)) == 4


async def test_ownership_and_server_side_admin_checks(platform):
    exam, attempt = await setup_exam(platform)
    view = await platform.question_view(123, attempt.id)
    for operation in [
        platform.save_answer(456, attempt.id, view["part_id"], "A"),
        platform.submit_attempt(456, attempt.id),
        platform.result(456, attempt.id),
        platform.question_view(456, attempt.id),
        platform.answer_review(456, attempt.id),
        platform.set_published(123, exam.id, False),
        platform.export_report(123, exam.id),
        platform.run_calibration(123, exam.id),
        platform.release_results(123, exam.id),
    ]:
        with pytest.raises(Forbidden):
            await operation


async def test_progress_survives_new_service_and_storage(platform):
    from quizbot.services import Platform

    exam, attempt = await setup_exam(platform, written=True)
    view = await platform.question_view(123, attempt.id)
    await platform.save_answer(123, attempt.id, view["part_id"], "A")
    restarted = Platform(platform.sessions, platform.settings)
    assert (await restarted.question_view(123, attempt.id))["answer"] == "A"
    key = StorageKey(bot_id=42, chat_id=123, user_id=123)
    storage = PostgresStorage(platform.sessions)
    await storage.set_state(key, "Taking:written")
    await storage.set_data(key, {"attempt_id": attempt.id})
    fresh = PostgresStorage(platform.sessions)
    assert await fresh.get_state(key) == "Taking:written"
    assert (await fresh.get_data(key))["attempt_id"] == attempt.id
    await asyncio.gather(fresh.update_data(key, {"a": 1}), fresh.update_data(key, {"b": 2}))
    assert (await fresh.get_data(key))["a"] == 1
    assert (await fresh.get_data(key))["b"] == 2


async def test_deadline_late_answer_commits_submission(platform):
    exam, attempt = await setup_exam(platform)
    view = await platform.question_view(123, attempt.id)
    async with platform.sessions.begin() as session:
        await session.execute(
            update(Attempt)
            .where(Attempt.id == attempt.id)
            .values(deadline=utcnow() - timedelta(seconds=1))
        )
    with pytest.raises(DomainError, match="Vaqt tugadi"):
        await platform.save_answer(123, attempt.id, view["part_id"], "A")
    result = await platform.result(123, attempt.id)
    assert result["status"] == "submitted" and result["raw"] == 0


async def test_manual_review_and_raw_release(platform):
    exam, attempt = await setup_exam(platform, written=True, review=True)
    view = await platform.question_view(123, attempt.id)
    await platform.save_answer(123, attempt.id, view["part_id"], "needs review")
    submitted = await platform.submit_attempt(123, attempt.id)
    assert submitted.raw_score is None
    await platform.close_exam(999, exam.id)
    with pytest.raises(DomainError, match="tekshiruvi"):
        await platform.release_results(999, exam.id)
    pending = await platform.pending_reviews(999, exam.id)
    assert len(pending) == 1
    await platform.review_grade(999, pending[0]["id"], 1, "Rubric verified")
    await platform.release_results(999, exam.id)
    result = await platform.result(123, attempt.id)
    assert result["raw"] == 1 and result["released"] and not result["calibrated"]
    assert len(await platform.answer_review(123, attempt.id)) == 4
    assert len(await platform.pending_notifications()) == 1
    with pytest.raises(DomainError, match="o‘zgartirilmaydi"):
        await platform.review_grade(999, pending[0]["id"], 0, "Cannot change")


async def test_keys_hidden_and_exam_frozen(platform):
    exam, attempt = await setup_exam(platform)
    view = await platform.question_view(123, attempt.id)
    assert "accepted" not in view and "key" not in view
    with pytest.raises(DomainError):
        await platform.answer_review(123, attempt.id)
    await platform.set_published(999, exam.id, False)
    with pytest.raises(DomainError):
        await platform.put_question(999, exam.id, spec().questions[0])
    with pytest.raises(DomainError):
        await platform.edit_exam(999, exam.id, policy=PolicySpec())


async def test_unverified_template_cannot_publish(platform):
    exam = await platform.import_exam(
        999,
        ExamSpec(
            title="Unverified",
            questions=[{"number": 1, "kind": "written", "needs_review": True, "parts": [{}]}],
        ),
    )
    with pytest.raises(DomainError, match="tekshiruvi"):
        await platform.set_published(999, exam.id, True)


async def test_report_and_formula_injection(platform):
    exam, attempt = await setup_exam(platform)
    await platform.register(123, first_name="=DANGEROUS()", last_name="Test")
    await platform.submit_attempt(123, attempt.id)
    report = await platform.report(999, exam.id)
    assert report["summary"]["participants"] == 1
    assert report["summary"]["average_t"] is None
    xlsx = await platform.export_report(999, exam.id, "xlsx")
    assert xlsx[:2] == b"PK"
    frame = pd.read_excel(io.BytesIO(xlsx), sheet_name="participants")
    assert frame.iloc[0]["full_name"] == "'=DANGEROUS() Test"
    csv = (await platform.export_report(999, exam.id, "csv")).decode("utf-8-sig")
    assert "'=DANGEROUS()" in csv and "summary" in csv and "items" in csv


async def test_calibration_release_reproducible_snapshot(platform):
    exam = await platform.import_exam(999, spec(n=8))
    rng = np.random.default_rng(68)
    n = 200
    matrix = (
        rng.random((n, 8)) < rasch_probability(rng.normal(size=(n, 1)), np.linspace(-1, 1, 8))
    ).astype(int)
    # Seed a synthetic reviewed cohort directly so this test exercises actual calibration and publication.
    async with platform.sessions.begin() as session:
        parts = list(
            await session.scalars(
                select(QuestionPart)
                .join(Question)
                .where(Question.exam_id == exam.id)
                .order_by(Question.number)
            )
        )
        for i, row in enumerate(matrix):
            user = User(telegram_id=1000 + i, full_name=f"Synthetic {i}")
            session.add(user)
            await session.flush()
            attempt = Attempt(
                exam_id=exam.id,
                user_id=user.id,
                status="submitted",
                deadline=utcnow(),
                submitted_at=utcnow(),
                raw_score=float(row.sum()),
                max_score=8.0,
            )
            session.add(attempt)
            await session.flush()
            for part, category in zip(parts, row, strict=True):
                session.add(
                    StudentResponse(
                        attempt_id=attempt.id, part_id=part.id, answer="A" if category else "B"
                    )
                )
                session.add(
                    GradingResult(
                        attempt_id=attempt.id,
                        part_id=part.id,
                        category=int(category),
                        raw_points=float(category),
                    )
                )
    await platform.close_exam(999, exam.id)
    first = await platform.run_calibration(999, exam.id)
    assert first["status"] == "ready", first
    second = await platform.run_calibration(999, exam.id)
    assert second["status"] == "ready", second
    async with platform.sessions() as session:
        a = await session.get(CalibrationRun, first["run_id"])
        b = await session.get(CalibrationRun, second["run_id"])
        assert a.snapshot["sha256"] == b.snapshot["sha256"]
        assert a.reference_mean == b.reference_mean
        assert a.reference_sd == b.reference_sd
        attempt = await session.scalar(select(Attempt).join(User).where(User.telegram_id == 1000))
    await platform.release_results(999, exam.id, first["run_id"])
    result = await platform.result(1000, attempt.id)
    assert result["calibrated"] and result["run_id"] == first["run_id"]
    assert result["t"] == pytest.approx(50 + 10 * result["z"])
    assert len(await platform.pending_notifications()) == 20
    with pytest.raises(DomainError):
        await platform.release_results(999, exam.id, second["run_id"])


async def test_stale_or_unstable_run_cannot_release(platform):
    exam, attempt = await setup_exam(platform)
    await platform.submit_attempt(123, attempt.id)
    await platform.close_exam(999, exam.id)
    async with platform.sessions.begin() as session:
        run = CalibrationRun(
            exam_id=exam.id,
            status="unstable",
            model="Rasch-1PL",
            algorithm_version="test",
            snapshot={},
        )
        session.add(run)
        await session.flush()
        run_id = run.id
    with pytest.raises(DomainError):
        await platform.release_results(999, exam.id, run_id)


async def test_regrading_invalidates_saved_calibration(platform):
    exam, attempt = await setup_exam(platform, written=True, review=True)
    view = await platform.question_view(123, attempt.id)
    await platform.save_answer(123, attempt.id, view["part_id"], "review this")
    await platform.submit_attempt(123, attempt.id)
    grade_id = (await platform.pending_reviews(999, exam.id))[0]["id"]
    await platform.review_grade(999, grade_id, 1, "Initial review")
    await platform.close_exam(999, exam.id)
    async with platform.sessions.begin() as session:
        run = CalibrationRun(
            exam_id=exam.id,
            status="ready",
            model="Rasch-1PL",
            algorithm_version="test",
            snapshot={},
        )
        session.add(run)
        await session.flush()
        run_id = run.id
    await platform.review_grade(999, grade_id, 0, "Corrected before release")
    async with platform.sessions() as session:
        assert (await session.get(CalibrationRun, run_id)).status == "stale"
    with pytest.raises(DomainError):
        await platform.release_results(999, exam.id, run_id)


async def test_worker_lease_prevents_conflicting_start_and_recovery(platform):
    exam, attempt = await setup_exam(platform)
    await platform.submit_attempt(123, attempt.id)
    await platform.close_exam(999, exam.id)
    async with platform.sessions.begin() as session:
        run = CalibrationRun(
            exam_id=exam.id,
            status="running",
            model="Rasch-1PL",
            algorithm_version="test",
            snapshot={},
        )
        session.add(run)
        await session.flush()
        run_id = run.id
    async with platform.calibration_lease() as acquired:
        assert acquired
        with pytest.raises(DomainError, match="Boshqa kalibrlash"):
            await platform.run_calibration(999, exam.id)
        await platform.recover_interrupted_runs()
        async with platform.sessions() as session:
            assert (await session.get(CalibrationRun, run_id)).status == "running"
    await platform.recover_interrupted_runs()
    async with platform.sessions() as session:
        assert (await session.get(CalibrationRun, run_id)).status == "failed"


async def test_weighted_multipart_keeps_parent_and_separate_categories(platform):
    exam_spec = ExamSpec(
        title="Multipart integration",
        questions=[
            {
                "number": 40,
                "kind": "multipart",
                "statement": "Synthetic two-part item",
                "parts": [
                    {"label": "A", "accepted": ["first"], "weight": 2.5},
                    {"label": "B", "accepted": ["second"], "weight": 3.5},
                ],
            }
        ],
    )
    exam = await platform.import_exam(999, exam_spec)
    await platform.set_published(999, exam.id, True)
    await platform.register(123, "Ali Vali")
    attempt = await platform.start_attempt(123, exam.id)
    a = await platform.question_view(123, attempt.id, 0)
    b = await platform.question_view(123, attempt.id, 1)
    assert a["number"] == b["number"] == 40
    assert a["label"] == "A" and b["label"] == "B"
    await platform.save_answer(123, attempt.id, a["part_id"], "first")
    await platform.save_answer(123, attempt.id, b["part_id"], "wrong")
    result = await platform.submit_attempt(123, attempt.id)
    assert result.raw_score == 2.5 and result.max_score == 6
    async with platform.sessions() as session:
        assert list(
            await session.scalars(select(GradingResult.category).order_by(GradingResult.part_id))
        ) == [1, 0]


async def test_foreign_part_rejected_and_sweeper_uses_persisted_deadline(platform):
    exam, attempt = await setup_exam(platform)
    other = await platform.import_exam(999, spec())
    async with platform.sessions() as session:
        foreign_part = await session.scalar(
            select(QuestionPart.id).join(Question).where(Question.exam_id == other.id).limit(1)
        )
    with pytest.raises(DomainError, match="tegishli emas"):
        await platform.save_answer(123, attempt.id, foreign_part, "A")
    async with platform.sessions.begin() as session:
        await session.execute(
            update(Attempt)
            .where(Attempt.id == attempt.id)
            .values(deadline=utcnow() - timedelta(minutes=1))
        )
    assert await platform.expire_attempts() == 1
    assert (await platform.result(123, attempt.id))["raw"] == 0


async def test_notification_success_is_persistent(platform):
    exam, attempt = await setup_exam(platform)
    await platform.submit_attempt(123, attempt.id)
    await platform.close_exam(999, exam.id)
    await platform.release_results(999, exam.id)
    pending = await platform.pending_notifications()
    assert len(pending) == 1
    await platform.mark_notification(pending[0][0], sent=True)
    assert not await platform.pending_notifications()
