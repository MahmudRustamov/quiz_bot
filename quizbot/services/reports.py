import io
from collections import Counter

import pandas as pd
from sqlalchemy import func, select

from quizbot.db.models import (
    Attempt,
    CalibrationRun,
    Exam,
    GradingResult,
    ItemParameter,
    Question,
    QuestionPart,
    StandardizedScore,
    StudentAbilityEstimate,
    StudentResponse,
    User,
)
from quizbot.domain import DomainError
from quizbot.services.base import Service


def safe_cell(value):
    """Prevent spreadsheet formula injection in both CSV and Excel exports."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


class ReportService(Service):
    async def report(self, actor: int, exam_id: int) -> dict:
        self.admin(actor)
        if self.settings.grading_strategy == "simple":
            return await self.simple_report(actor, exam_id)
        async with self.sessions() as session:
            exam = await session.get(Exam, exam_id)
            if exam is None:
                raise DomainError("Test topilmadi.")
            attempts = (
                await session.execute(
                    select(Attempt, User)
                    .join(User)
                    .where(Attempt.exam_id == exam_id)
                    .order_by(Attempt.id)
                )
            ).all()
            latest = await session.scalar(
                select(CalibrationRun)
                .where(CalibrationRun.exam_id == exam_id)
                .order_by(CalibrationRun.id.desc())
                .limit(1)
            )
            run = (
                await session.get(CalibrationRun, exam.released_run_id)
                if exam.released_run_id
                else latest
            )
            valid = run is not None and run.status == "ready"
            scores = (
                {
                    s.attempt_id: s
                    for s in await session.scalars(
                        select(StandardizedScore).where(StandardizedScore.run_id == run.id)
                    )
                }
                if valid
                else {}
            )
            abilities = (
                {
                    a.attempt_id: a
                    for a in await session.scalars(
                        select(StudentAbilityEstimate).where(
                            StudentAbilityEstimate.run_id == run.id
                        )
                    )
                }
                if valid
                else {}
            )
            participants = [
                {
                    "attempt_id": a.id,
                    "telegram_id": u.telegram_id,
                    "full_name": u.full_name,
                    "status": a.status,
                    "raw_score": a.raw_score,
                    "max_score": a.max_score,
                    "theta": abilities[a.id].theta if a.id in abilities else None,
                    "posterior_sd": abilities[a.id].posterior_sd if a.id in abilities else None,
                    "t_score": scores[a.id].t_score if a.id in scores else None,
                    "z_score": scores[a.id].z_score if a.id in scores else None,
                    "grade": scores[a.id].grade if a.id in scores else None,
                }
                for a, u in attempts
            ]
            raw = [a.raw_score for a, _u in attempts if a.raw_score is not None]
            parameters = (
                {
                    p.item_key: p
                    for p in await session.scalars(
                        select(ItemParameter).where(ItemParameter.run_id == run.id)
                    )
                }
                if valid
                else {}
            )
            rows = (
                await session.execute(
                    select(QuestionPart, Question)
                    .join(Question)
                    .where(Question.exam_id == exam_id)
                    .order_by(Question.number, QuestionPart.label)
                )
            ).all()
            aggregates = {
                part_id: (total, count)
                for part_id, total, count in (
                    await session.execute(
                        select(
                            GradingResult.part_id,
                            func.sum(GradingResult.category),
                            func.count(GradingResult.category),
                        )
                        .join(Attempt)
                        .where(Attempt.exam_id == exam_id)
                        .group_by(GradingResult.part_id)
                    )
                ).all()
            }
            response_rows = (
                await session.execute(
                    select(StudentResponse.part_id, StudentResponse.answer, func.count())
                    .join(Attempt)
                    .where(Attempt.exam_id == exam_id, Attempt.status == "submitted")
                    .group_by(StudentResponse.part_id, StudentResponse.answer)
                )
            ).all()
            distributions = [
                {"part_id": p, "answer": answer, "count": count}
                for p, answer, count in response_rows
            ]
            items = []
            for p, q in rows:
                total, count = aggregates.get(p.id, (0, 0))
                parameter = parameters.get(f"q:{q.id}" if q.pcm else f"p:{p.id}")
                items.append(
                    {
                        "question": q.number,
                        "part": p.label,
                        "part_id": p.id,
                        "graded_count": count,
                        "percent_correct": 100 * total / count if count else None,
                        "steps": parameter.steps if parameter else None,
                        "standard_errors": parameter.standard_errors if parameter else None,
                        "raw_weight": p.weight,
                    }
                )
            ranked = sorted(
                [i for i in items if i["percent_correct"] is not None],
                key=lambda i: i["percent_correct"],
            )
            summary = {
                "exam_id": exam_id,
                "title": exam.title,
                "participants": len(attempts),
                "submitted": sum(a.status == "submitted" for a, _u in attempts),
                "pending_manual_review": await session.scalar(
                    select(func.count())
                    .select_from(GradingResult)
                    .join(Attempt)
                    .where(Attempt.exam_id == exam_id, GradingResult.pending.is_(True))
                ),
                "average_raw": sum(raw) / len(raw) if raw else None,
                "average_t": sum(s.t_score for s in scores.values()) / len(scores)
                if scores
                else None,
                "grades": dict(Counter(s.grade for s in scores.values())),
                "calibration_status": run.status if run else "unavailable",
                "run_id": run.id if run else None,
                "results_released": exam.results_released,
                "hardest": [(i["question"], i["part"]) for i in ranked[:5]],
                "easiest": [(i["question"], i["part"]) for i in ranked[-5:][::-1]],
            }
            return {
                "summary": summary,
                "participants": participants,
                "items": items,
                "responses": distributions,
                "calibration": {
                    "diagnostics": run.diagnostics,
                    "reference_mean": run.reference_mean,
                    "reference_sd": run.reference_sd,
                    "algorithm": run.algorithm_version,
                    "snapshot_sha256": run.snapshot.get("sha256"),
                }
                if run
                else {},
            }

    async def export_report(self, actor: int, exam_id: int, format: str = "xlsx") -> bytes:
        self.admin(actor)
        if self.settings.grading_strategy == "simple" and format == "xlsx":
            return await self.export_simple_excel(actor, exam_id)
        if format not in ("csv", "xlsx"):
            raise DomainError("Hisobot formati csv yoki xlsx bo‘lsin.")
        report = await self.report(actor, exam_id)
        return await __import__("asyncio").to_thread(render_report, report, format)


def render_report(report: dict, format: str) -> bytes:
    if format == "csv":
        # Single long-form table includes summary, participants, items, distributions.
        rows = []
        for section, data in report.items():
            records = data if isinstance(data, list) else [data]
            rows.extend({"section": section, **row} for row in records)
        return pd.DataFrame(rows).map(safe_cell).to_csv(index=False).encode("utf-8-sig")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, data in report.items():
            rows = data if isinstance(data, list) else [data]
            frame = pd.DataFrame(rows)
            for column in frame:
                frame[column] = frame[column].map(
                    lambda v: str(v) if isinstance(v, (dict, list, tuple)) else v
                )
            frame.map(safe_cell).to_excel(writer, sheet_name=name, index=False)
    return buffer.getvalue()
