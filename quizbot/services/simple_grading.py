"""Response-based statistics and an independent simple-results release policy."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import fsum
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from quizbot.db.models import (
    AnswerKey,
    Attempt,
    Exam,
    GradingResult,
    Question,
    QuestionPart,
    ResultNotification,
    StudentResponse,
    User,
    utcnow,
)
from quizbot.domain import DomainError
from quizbot.grading import normalize_answer
from quizbot.services.base import Service

Outcome = Literal["correct", "incorrect", "partial", "unanswered", "pending"]


@dataclass(frozen=True)
class ElementResult:
    question_id: int
    number: int
    part_id: int
    label: str
    state: Outcome
    answer: str | None
    accepted: list[str]
    points: float | None
    maximum: float
    statement: str = ""
    prompt: str = ""
    explanation: str = ""
    image_file_id: str | None = None


def summarize(elements: list[ElementResult]) -> dict:
    """Parent and element counts are independent of raw weights and raw totals.

    A parent is unanswered only when all parts are blank, correct only when all
    parts are correct, and partial when at least one (but not all) is correct.
    Otherwise a resolved parent with any submitted response is incorrect.
    Pending grading is never silently counted as an incorrect response.
    """
    groups = defaultdict(list)
    for element in elements:
        groups[element.question_id].append(element)
    parents = {}
    for question_id, parts in groups.items():
        states = [p.state for p in parts]
        if "pending" in states:
            state = "pending"
        elif all(s == "unanswered" for s in states):
            state = "unanswered"
        elif all(s == "correct" for s in states):
            state = "correct"
        elif "correct" in states:
            state = "partial"
        else:
            state = "incorrect"
        parents[question_id] = state
    question_counts = Counter(parents.values())
    element_counts = Counter(e.state for e in elements)
    return {
        "total_questions": len(groups),
        **{
            f"{state}_questions": question_counts[state]
            for state in ("correct", "incorrect", "partial", "unanswered", "pending")
        },
        "total_elements": len(elements),
        **{
            f"{state}_elements": element_counts[state]
            for state in ("correct", "incorrect", "unanswered", "pending")
        },
        "percentage": 100 * question_counts["correct"] / len(groups) if groups else 0.0,
        "element_percentage": 100 * element_counts["correct"] / len(elements) if elements else 0.0,
        "raw_score": None if element_counts["pending"] else fsum(e.points or 0.0 for e in elements),
        "maximum_raw_score": fsum(e.maximum for e in elements),
        "parent_states": parents,
    }


async def load_elements(session, attempt: Attempt) -> list[ElementResult]:
    rows = (
        await session.execute(
            select(Question, QuestionPart, AnswerKey, StudentResponse, GradingResult)
            .join(QuestionPart, QuestionPart.question_id == Question.id)
            .join(AnswerKey, AnswerKey.part_id == QuestionPart.id)
            .outerjoin(
                StudentResponse,
                (StudentResponse.part_id == QuestionPart.id)
                & (StudentResponse.attempt_id == attempt.id),
            )
            .outerjoin(
                GradingResult,
                (GradingResult.part_id == QuestionPart.id)
                & (GradingResult.attempt_id == attempt.id),
            )
            .where(Question.exam_id == attempt.exam_id)
            .order_by(Question.number, QuestionPart.label)
        )
    ).all()
    return [element_from_row(*row) for row in rows]


def element_from_row(q, part, key, response, grade) -> ElementResult:
    answer = response.answer if response else None
    if grade is None or grade.pending or grade.category is None or grade.raw_points is None:
        state = "pending"
    elif not answer or not normalize_answer(answer):
        state = "unanswered"
    else:
        state = "correct" if grade.category == 1 else "incorrect"
    explanation = q.rubric.get("explanation", "")
    if isinstance(explanation, dict):
        explanation = explanation.get(part.label, "")
    if grade is not None and grade.note:
        explanation = f"{explanation}\nTekshiruvchi izohi: {grade.note}".strip()
    return ElementResult(
        q.id,
        q.number,
        part.id,
        part.label,
        state,
        answer,
        key.accepted,
        grade.raw_points if grade else None,
        part.weight,
        q.statement,
        part.prompt,
        str(explanation or ""),
        q.image_file_id,
    )


def release_state(attempt, exam, metrics, settings) -> str:
    if attempt.status != "submitted":
        return "in_progress"
    if metrics["pending_elements"]:
        return "reviewing"
    policy = exam.simple_release_policy or settings.simple_release_policy
    if (
        attempt.simple_released_at
        or exam.simple_results_released
        or exam.results_released
        or policy == "immediate"
    ):
        return "released"
    return "held"


async def queue_notification(session, attempt_id):
    statement = insert(ResultNotification).values(attempt_id=attempt_id)
    await session.execute(
        statement.on_conflict_do_nothing(index_elements=[ResultNotification.attempt_id])
    )


async def maybe_release_simple(session, attempt, exam, settings) -> None:
    if (
        settings.grading_strategy != "simple"
        or attempt.status != "submitted"
        or attempt.raw_score is None
    ):
        return
    if (
        exam.simple_results_released
        or (exam.simple_release_policy or settings.simple_release_policy) == "immediate"
    ):
        if attempt.simple_released_at is None:
            attempt.simple_released_at = utcnow()
            await queue_notification(session, attempt.id)


class SimpleGradingService(Service):
    async def simple_result(self, actor: int, attempt_id: int) -> dict:
        async with self.sessions.begin() as session:
            attempt = await self.owned_attempt(session, attempt_id, actor, lock=True)
            exam = await session.get(Exam, attempt.exam_id)
            user = await session.get(User, attempt.user_id)
            metrics = summarize(await load_elements(session, attempt))
            state = release_state(attempt, exam, metrics, self.settings)
            if state == "released" and attempt.simple_released_at is None:
                attempt.simple_released_at = utcnow()
            return {
                "attempt_id": attempt.id,
                "exam_id": exam.id,
                "title": exam.title,
                "subject": exam.subject,
                "full_name": user.full_name,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "status": attempt.status,
                "release_state": state,
                "released": state == "released",
                "review_enabled": state == "released" and exam.answer_review_enabled,
                "calibrated": False,
                "strategy": "simple",
                "metrics": metrics if state == "released" else None,
                "raw": metrics["raw_score"] if state == "released" else None,
                "maximum": metrics["maximum_raw_score"],
                "submitted_at": attempt.submitted_at,
            }

    async def set_result_policy(
        self, actor: int, exam_id: int, policy: str, review_enabled: bool = True
    ):
        self.admin(actor)
        if policy not in ("immediate", "manual"):
            raise DomainError("Natija siyosati immediate yoki manual bo‘lsin.")
        async with self.sessions.begin() as session:
            exam = await self.locked_exam(session, exam_id)
            exam.simple_release_policy, exam.answer_review_enabled = policy, review_enabled
            self.audit(
                session,
                actor,
                "simple.policy",
                exam_id=exam_id,
                policy=policy,
                review_enabled=review_enabled,
            )

    async def release_simple_results(self, actor: int, exam_id: int):
        self.admin(actor)
        async with self.sessions.begin() as session:
            exam = await self.locked_exam(session, exam_id)
            exam.simple_results_released = True
            for attempt in await session.scalars(
                select(Attempt).where(Attempt.exam_id == exam_id, Attempt.status == "submitted")
            ):
                await maybe_release_simple(session, attempt, exam, self.settings)
            self.audit(session, actor, "simple.release", exam_id=exam_id)

    async def set_subject(self, actor: int, exam_id: int, subject: str):
        self.admin(actor)
        if not 1 <= len(subject.strip()) <= 200:
            raise DomainError("Fan nomi 1–200 belgi bo‘lsin.")
        async with self.sessions.begin() as session:
            exam = await self.locked_exam(session, exam_id)
            exam.subject = subject.strip()
            self.audit(session, actor, "exam.subject", exam_id=exam_id)
