from datetime import UTC, timedelta

from sqlalchemy import func, select, update

from quizbot.db.models import (
    AnswerKey,
    Attempt,
    CalibrationRun,
    Exam,
    ExamMaterial,
    GradingResult,
    Question,
    QuestionMaterial,
    QuestionOption,
    QuestionPart,
    StandardizedScore,
    StudentAbilityEstimate,
    StudentResponse,
    User,
    utcnow,
)
from quizbot.domain import DomainError
from quizbot.grading import grade_answer
from quizbot.services.base import Service
from quizbot.services.simple_grading import (
    load_elements,
    maybe_release_simple,
    release_state,
    summarize,
)


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def elements(session, exam_id):
    return (
        await session.execute(
            select(QuestionPart, Question, AnswerKey)
            .join(Question, QuestionPart.question_id == Question.id)
            .join(AnswerKey, AnswerKey.part_id == QuestionPart.id)
            .where(Question.exam_id == exam_id)
            .order_by(Question.number, QuestionPart.label)
        )
    ).all()


class AttemptService(Service):
    async def start_attempt(self, actor: int, exam_id: int) -> Attempt:
        async with self.sessions.begin() as session:
            exam = await self.locked_exam(session, exam_id)
            user = await session.scalar(select(User).where(User.telegram_id == actor))
            if user is None:
                raise DomainError("Avval /start orqali ro‘yxatdan o‘ting.")
            if not user.first_name or not user.last_name:
                raise DomainError("Avval /start orqali ism va familiyangizni kiriting.")
            existing = await session.scalar(
                select(Attempt).where(Attempt.exam_id == exam_id, Attempt.user_id == user.id)
            )
            if existing:
                return existing
            if not exam.published or exam.closed:
                raise DomainError("Bu test hozir qabul qilmayapti.")
            attempt = Attempt(
                exam_id=exam_id,
                user_id=user.id,
                deadline=utcnow() + timedelta(minutes=exam.duration_minutes),
            )
            session.add(attempt)
            await session.flush()
            return attempt

    async def save_answer(self, actor: int, attempt_id: int, part_id: int, answer: str):
        if len(answer) > 2000:
            raise DomainError("Javob 2000 belgidan oshmasin.")
        expired = False
        async with self.sessions.begin() as session:
            attempt = await self.owned_attempt(session, attempt_id, actor, lock=True)
            if attempt.status != "in_progress":
                raise DomainError("Test allaqachon topshirilgan.")
            if utcnow() >= aware(attempt.deadline):
                await self._submit(session, attempt)
                expired = True
            else:
                row = (
                    await session.execute(
                        select(QuestionPart, Question)
                        .join(Question)
                        .where(QuestionPart.id == part_id, Question.exam_id == attempt.exam_id)
                    )
                ).first()
                if row is None:
                    raise DomainError("Savol ushbu testga tegishli emas.")
                _, question = row
                if question.kind in ("mcq", "matching"):
                    labels = set(
                        await session.scalars(
                            select(QuestionOption.label).where(
                                QuestionOption.question_id == question.id
                            )
                        )
                    )
                    if answer not in labels:
                        raise DomainError("Berilgan variantlardan birini tanlang.")
                response = await session.scalar(
                    select(StudentResponse).where(
                        StudentResponse.attempt_id == attempt_id, StudentResponse.part_id == part_id
                    )
                )
                if response:
                    response.answer = answer
                else:
                    session.add(
                        StudentResponse(attempt_id=attempt_id, part_id=part_id, answer=answer)
                    )
        if expired:
            raise DomainError("Vaqt tugadi. Saqlangan javoblar topshirildi.")

    async def question_view(self, actor: int, attempt_id: int, index: int = 0) -> dict:
        async with self.sessions.begin() as session:
            attempt = await self.owned_attempt(session, attempt_id, actor, lock=True)
            if attempt.status == "in_progress" and utcnow() >= aware(attempt.deadline):
                await self._submit(session, attempt)
            if attempt.status != "in_progress":
                return {"submitted": True, "attempt_id": attempt_id}
            rows = await elements(session, attempt.exam_id)
            if not rows:
                raise DomainError("Test savollari topilmadi.")
            index = min(max(0, index), len(rows) - 1)
            part, question, _key = rows[index]
            options = list(
                await session.scalars(
                    select(QuestionOption)
                    .where(QuestionOption.question_id == question.id)
                    .order_by(QuestionOption.label)
                )
            )
            answers = {
                r.part_id: r.answer
                for r in await session.scalars(
                    select(StudentResponse).where(StudentResponse.attempt_id == attempt_id)
                )
            }
            return {
                "submitted": False,
                "attempt_id": attempt_id,
                "part_id": part.id,
                "index": index,
                "count": len(rows),
                "number": question.number,
                "label": part.label,
                "prompt": part.prompt,
                "statement": question.statement,
                "options": [(o.label, o.text) for o in options],
                "image_file_id": question.image_file_id,
                "materials": [
                    {
                        "key": material.key,
                        "title": material.title,
                        "text": material.text,
                        "source_pages": material.source_pages,
                    }
                    for material in await session.scalars(
                        select(ExamMaterial)
                        .join(QuestionMaterial, QuestionMaterial.material_id == ExamMaterial.id)
                        .where(QuestionMaterial.question_id == question.id)
                        .order_by(QuestionMaterial.position)
                    )
                ],
                "answer": answers.get(part.id),
                "unanswered": [
                    i for i, (p, _q, _k) in enumerate(rows) if not answers.get(p.id, "").strip()
                ],
                "deadline": aware(attempt.deadline),
            }

    async def submit_attempt(self, actor: int, attempt_id: int) -> Attempt:
        async with self.sessions.begin() as session:
            attempt = await self.owned_attempt(session, attempt_id, actor, lock=True)
            if attempt.status == "in_progress":
                await self._submit(session, attempt)
            return attempt

    async def _submit(self, session, attempt):
        rows = await elements(session, attempt.exam_id)
        responses = {
            r.part_id: r.answer
            for r in await session.scalars(
                select(StudentResponse).where(StudentResponse.attempt_id == attempt.id)
            )
        }
        total, maximum, pending = 0.0, 0.0, False
        for part, _question, key in rows:
            result = grade_answer(
                responses.get(part.id),
                key.accepted,
                weight=part.weight,
                ignore_case=key.ignore_case,
                manual_review=key.manual_review,
            )
            session.add(
                GradingResult(
                    attempt_id=attempt.id,
                    part_id=part.id,
                    category=result.category,
                    raw_points=result.points,
                    pending=result.pending,
                )
            )
            total += result.points or 0
            maximum += part.weight
            pending |= result.pending
        attempt.raw_score = None if pending else total
        attempt.max_score = maximum
        attempt.status = "submitted"
        attempt.submitted_at = utcnow()
        await session.flush()
        await maybe_release_simple(
            session, attempt, await session.get(Exam, attempt.exam_id), self.settings
        )

    async def expire_attempts(self) -> int:
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(Attempt.id, User.telegram_id)
                    .join(User)
                    .where(Attempt.status == "in_progress", Attempt.deadline <= utcnow())
                    .limit(100)
                )
            ).all()
        for attempt_id, actor in rows:
            await self.submit_attempt(actor, attempt_id)
        return len(rows)

    async def pending_reviews(self, actor: int, exam_id: int, page: int = 0) -> list[dict]:
        self.admin(actor)
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(
                        GradingResult,
                        StudentResponse.answer,
                        Question.number,
                        QuestionPart.label,
                        Question.rubric,
                    )
                    .join(Attempt, Attempt.id == GradingResult.attempt_id)
                    .join(QuestionPart, QuestionPart.id == GradingResult.part_id)
                    .join(Question, Question.id == QuestionPart.question_id)
                    .outerjoin(
                        StudentResponse,
                        (StudentResponse.attempt_id == GradingResult.attempt_id)
                        & (StudentResponse.part_id == GradingResult.part_id),
                    )
                    .where(Attempt.exam_id == exam_id, GradingResult.pending.is_(True))
                    .order_by(GradingResult.id)
                    .offset(max(page, 0) * 5)
                    .limit(5)
                )
            ).all()
            return [
                {
                    "id": r.id,
                    "attempt_id": r.attempt_id,
                    "answer": answer,
                    "number": number,
                    "label": label,
                    "rubric": rubric,
                }
                for r, answer, number, label, rubric in rows
            ]

    async def review_grade(self, actor: int, grade_id: int, category: int, note: str):
        self.admin(actor)
        if category not in (0, 1) or not note.strip() or len(note) > 2000:
            raise DomainError("Baholash 0 yoki 1, izoh esa 1–2000 belgi bo‘lsin.")
        async with self.sessions.begin() as session:
            result = await session.get(GradingResult, grade_id)
            if result is None:
                raise DomainError("Baholash topilmadi.")
            attempt = await session.get(Attempt, result.attempt_id)
            exam = await self.locked_exam(session, attempt.exam_id)
            if exam.results_released or attempt.simple_released_at:
                raise DomainError("E’lon qilingan natija o‘zgartirilmaydi.")
            running = await session.scalar(
                select(CalibrationRun.id).where(
                    CalibrationRun.exam_id == exam.id, CalibrationRun.status == "running"
                )
            )
            if running:
                raise DomainError("Kalibrlash tugashini kuting.")
            await session.execute(select(Attempt).where(Attempt.id == attempt.id).with_for_update())
            await session.refresh(result)
            part = await session.get(QuestionPart, result.part_id)
            result.category, result.raw_points = category, category * part.weight
            result.pending, result.reviewer_id, result.note = False, actor, note.strip()
            await session.flush()
            pending = await session.scalar(
                select(func.count())
                .select_from(GradingResult)
                .where(GradingResult.attempt_id == attempt.id, GradingResult.pending.is_(True))
            )
            attempt.raw_score = (
                None
                if pending
                else await session.scalar(
                    select(func.sum(GradingResult.raw_points)).where(
                        GradingResult.attempt_id == attempt.id
                    )
                )
            )
            await session.execute(
                update(CalibrationRun)
                .where(
                    CalibrationRun.exam_id == exam.id,
                    CalibrationRun.status.in_(["ready", "unstable"]),
                )
                .values(status="stale")
            )
            self.audit(
                session,
                actor,
                "grade.review",
                grade_id=grade_id,
                category=category,
                note=note.strip(),
            )
            await maybe_release_simple(session, attempt, exam, self.settings)

    async def history(self, actor: int, page: int = 0) -> list[dict]:
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(Attempt.id, Exam.title, Attempt.status)
                    .join(User, User.id == Attempt.user_id)
                    .join(Exam, Exam.id == Attempt.exam_id)
                    .where(User.telegram_id == actor)
                    .order_by(Attempt.id.desc())
                    .offset(max(0, page) * 8)
                    .limit(8)
                )
            ).all()
            return [{"id": i, "title": title, "status": status} for i, title, status in rows]

    async def result(self, actor: int, attempt_id: int) -> dict:
        from quizbot.services.scoring import grading_strategy

        return await grading_strategy(self).result(actor, attempt_id)

    async def rasch_result(self, actor: int, attempt_id: int) -> dict:
        async with self.sessions() as session:
            attempt = await self.owned_attempt(session, attempt_id, actor)
            exam = await session.get(Exam, attempt.exam_id)
            result = {
                "title": exam.title,
                "status": attempt.status,
                "raw": attempt.raw_score,
                "maximum": attempt.max_score,
                "released": exam.results_released,
                "calibrated": False,
            }
            if exam.results_released and exam.released_run_id:
                row = (
                    await session.execute(
                        select(StudentAbilityEstimate, StandardizedScore)
                        .join(
                            StandardizedScore,
                            (StandardizedScore.attempt_id == StudentAbilityEstimate.attempt_id)
                            & (StandardizedScore.run_id == StudentAbilityEstimate.run_id),
                        )
                        .where(
                            StudentAbilityEstimate.attempt_id == attempt_id,
                            StudentAbilityEstimate.run_id == exam.released_run_id,
                        )
                    )
                ).first()
                if row:
                    ability, score = row
                    result.update(
                        calibrated=True,
                        theta=ability.theta,
                        posterior_sd=ability.posterior_sd,
                        z=score.z_score,
                        t=score.t_score,
                        grade=score.grade,
                        run_id=exam.released_run_id,
                    )
            return result

    async def answer_review(self, actor: int, attempt_id: int, page: int = 0) -> list[dict]:
        async with self.sessions() as session:
            attempt = await self.owned_attempt(session, attempt_id, actor)
            exam = await session.get(Exam, attempt.exam_id)
            if self.settings.grading_strategy == "simple":
                metrics = summarize(await load_elements(session, attempt))
                allowed = release_state(attempt, exam, metrics, self.settings) == "released"
            else:
                allowed = exam.results_released and attempt.status == "submitted"
            if not allowed or not exam.answer_review_enabled:
                raise DomainError("Javoblar natijalar e’lon qilingandan keyin ochiladi.")
            rows = (
                await session.execute(
                    select(GradingResult, QuestionPart, Question, AnswerKey, StudentResponse.answer)
                    .join(QuestionPart, QuestionPart.id == GradingResult.part_id)
                    .join(Question, Question.id == QuestionPart.question_id)
                    .join(AnswerKey, AnswerKey.part_id == QuestionPart.id)
                    .outerjoin(
                        StudentResponse,
                        (StudentResponse.part_id == GradingResult.part_id)
                        & (StudentResponse.attempt_id == attempt_id),
                    )
                    .where(GradingResult.attempt_id == attempt_id)
                    .order_by(Question.number, QuestionPart.label)
                    .offset(max(0, page) * 5)
                    .limit(5)
                )
            ).all()
            return [
                {
                    "number": q.number,
                    "label": p.label,
                    "answer": answer,
                    "accepted": key.accepted,
                    "category": g.category,
                    "points": g.raw_points,
                    "note": g.note,
                    "rubric": q.rubric,
                }
                for g, p, q, key, answer in rows
            ]

    async def review_page(self, actor: int, attempt_id: int, kind: str, index: int = 0) -> dict:
        if kind not in {"wrong", "correct", "all"}:
            raise DomainError("Javoblar bo‘limi topilmadi.")
        async with self.sessions() as session:
            attempt = await self.owned_attempt(session, attempt_id, actor)
            exam = await session.get(Exam, attempt.exam_id)
            answers = await load_elements(session, attempt)
            allowed = (
                release_state(attempt, exam, summarize(answers), self.settings) == "released"
                if self.settings.grading_strategy == "simple"
                else exam.results_released and attempt.status == "submitted"
            )
            if not allowed or not exam.answer_review_enabled:
                raise DomainError("Javoblarni ko‘rish hali yoqilmagan.")
            answers = [
                a
                for a in answers
                if kind == "all"
                or (kind == "correct" and a.state == "correct")
                or (kind == "wrong" and a.state == "incorrect")
            ]
            index = min(max(0, index), max(0, len(answers) - 1))
            if not answers:
                return {"count": 0, "index": 0, "answer": None, "materials": [], "options": []}
            answer = answers[index]
            materials = list(
                await session.scalars(
                    select(ExamMaterial)
                    .join(QuestionMaterial, QuestionMaterial.material_id == ExamMaterial.id)
                    .where(QuestionMaterial.question_id == answer.question_id)
                    .order_by(QuestionMaterial.position)
                )
            )
            options = list(
                await session.scalars(
                    select(QuestionOption)
                    .where(QuestionOption.question_id == answer.question_id)
                    .order_by(QuestionOption.label)
                )
            )
            return {
                "count": len(answers),
                "index": index,
                "answer": answer,
                "options": [(o.label, o.text) for o in options],
                "materials": [
                    {"key": m.key, "title": m.title, "text": m.text, "source_pages": m.source_pages}
                    for m in materials
                ],
            }

    async def review_materials(self, actor: int, attempt_id: int, kind: str, index: int = 0):
        return (await self.review_page(actor, attempt_id, kind, index))["materials"]

    async def leaderboard(self, actor: int, exam_id: int, page: int = 0) -> list[dict]:
        async with self.sessions() as session:
            exam = await session.get(Exam, exam_id)
            if exam is None:
                raise DomainError("Reyting hali e’lon qilinmagan.")
            if self.settings.grading_strategy == "rasch" and not exam.results_released:
                raise DomainError("Reyting hali e’lon qilinmagan.")
            # Pseudonymous IDs; do not reveal students' full names to other students.
            query = (
                select(Attempt.id, Attempt.raw_score)
                .where(
                    Attempt.exam_id == exam_id,
                    Attempt.status == "submitted",
                    Attempt.raw_score.is_not(None),
                )
                .order_by(Attempt.raw_score.desc(), Attempt.id)
            )
            if self.settings.grading_strategy == "simple" and not (
                exam.simple_results_released
                or exam.results_released
                or (exam.simple_release_policy or self.settings.simple_release_policy)
                == "immediate"
            ):
                query = query.where(Attempt.simple_released_at.is_not(None))
            rows = (await session.execute(query.offset(max(0, page) * 10).limit(10))).all()
            return [{"attempt_id": i, "raw": raw} for i, raw in rows]
