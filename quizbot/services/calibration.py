import asyncio
import hashlib
import json
import os
import sys
from contextlib import asynccontextmanager

from sqlalchemy import func, select, text, update

from quizbot.db.models import (
    Attempt,
    CalibrationRun,
    GradingPolicy,
    GradingResult,
    ItemParameter,
    ResultNotification,
    StandardizedScore,
    StudentAbilityEstimate,
)
from quizbot.domain import DomainError
from quizbot.psychometrics.models import ALGORITHM_VERSION
from quizbot.services.attempts import elements
from quizbot.services.base import Service


class CalibrationService(Service):
    @asynccontextmanager
    async def calibration_lease(self):
        """A dedicated connection holds the global worker lease across transactions."""
        async with self.sessions.kw["bind"].connect() as connection:
            postgres = connection.dialect.name == "postgresql"
            acquired = (
                bool(await connection.scalar(text("SELECT pg_try_advisory_lock(610442002)")))
                if postgres
                else True
            )
            await connection.commit()
            try:
                yield acquired
            finally:
                if acquired and postgres:
                    await connection.execute(text("SELECT pg_advisory_unlock(610442002)"))

    async def calibration_status(self, actor: int, exam_id: int) -> list[CalibrationRun]:
        self.admin(actor)
        async with self.sessions() as session:
            return list(
                await session.scalars(
                    select(CalibrationRun)
                    .where(CalibrationRun.exam_id == exam_id)
                    .order_by(CalibrationRun.id.desc())
                    .limit(5)
                )
            )

    @staticmethod
    async def _complete_cohort(session, exam):
        if not exam.closed:
            raise DomainError("Avval testga yangi kirishlarni yoping.")
        active = await session.scalar(
            select(func.count())
            .select_from(Attempt)
            .where(Attempt.exam_id == exam.id, Attempt.status == "in_progress")
        )
        if active:
            raise DomainError("Faol urinishlar tugashini kuting.")
        pending = await session.scalar(
            select(func.count())
            .select_from(GradingResult)
            .join(Attempt)
            .where(Attempt.exam_id == exam.id, GradingResult.pending.is_(True))
        )
        if pending:
            raise DomainError("Yozma javoblar tekshiruvi hali tugamagan.")

    async def run_calibration(self, actor: int, exam_id: int) -> dict:
        self.admin(actor)
        if self.settings.grading_strategy != "rasch":
            raise DomainError(
                "Hozir oddiy baholash rejimi yoqilgan. Rasch tahlili vaqtincha o‘chirilgan."
            )
        async with self.calibration_lease() as acquired:
            if not acquired:
                raise DomainError("Boshqa kalibrlash ishlamoqda. Tugashini kuting.")
            return await self._run_calibration(actor, exam_id)

    async def _run_calibration(self, actor: int, exam_id: int) -> dict:
        self.admin(actor)
        async with self.sessions.begin() as session:
            exam = await self.locked_exam(session, exam_id)
            if exam.results_released:
                raise DomainError("Natijalar allaqachon e’lon qilingan.")
            await self._complete_cohort(session, exam)
            running = await session.scalar(
                select(CalibrationRun.id).where(CalibrationRun.status == "running").limit(1)
            )
            if running:
                raise DomainError("Boshqa kalibrlash ishlamoqda. Tugashini kuting.")
            policy = dict((await session.get(GradingPolicy, exam.policy_id)).config)
            policy["min_students"] = max(
                policy["min_students"], self.settings.calibration_min_students
            )
            attempts = list(
                await session.scalars(
                    select(Attempt)
                    .where(Attempt.exam_id == exam_id, Attempt.status == "submitted")
                    .order_by(Attempt.id)
                )
            )
            if not policy["min_students"] <= len(attempts) <= 10000:
                raise DomainError(
                    f"Kalibrlash uchun {policy['min_students']}–10000 ta tugallangan urinish kerak."
                )
            rows = await elements(session, exam_id)
            groups: dict[str, list[int]] = {}
            for p, q, _key in rows:
                if q.pcm and not policy["pcm_assumptions_confirmed"]:
                    raise DomainError("PCM uchun model tuzilishi tekshirilishi kerak.")
                key = f"q:{q.id}" if q.pcm else f"p:{p.id}"
                groups.setdefault(key, []).append(p.id)
            if not 3 <= len(groups) <= 100:
                raise DomainError("Kalibrlash 3–100 ta psixometrik elementni qo‘llaydi.")
            grades = {
                (g.attempt_id, g.part_id): g.category
                for g in await session.scalars(
                    select(GradingResult).join(Attempt).where(Attempt.exam_id == exam_id)
                )
            }
            observed = set(
                (
                    await session.execute(
                        select(GradingResult.attempt_id, GradingResult.part_id)
                        .join(Attempt)
                        .where(Attempt.exam_id == exam_id)
                    )
                ).all()
            )
            # Distinguish a recorded wrong response from an unanswered element.
            from quizbot.db.models import StudentResponse

            responses = {
                (r.attempt_id, r.part_id): bool(r.answer.strip())
                for r in await session.scalars(
                    select(StudentResponse).join(Attempt).where(Attempt.exam_id == exam_id)
                )
            }
            matrix = []
            for attempt in attempts:
                row = []
                for parts in groups.values():
                    if any(
                        (attempt.id, p) not in observed or grades[attempt.id, p] is None
                        for p in parts
                    ):
                        raise DomainError("Baholash yozuvlari to‘liq emas.")
                    # PCM omission drops the whole parent if any component is missing.
                    missing = any(not responses.get((attempt.id, p), False) for p in parts)
                    row.append(
                        None
                        if missing and policy["missing_policy"] == "omit"
                        else sum(grades[attempt.id, p] for p in parts)
                    )
                matrix.append(row)
            snapshot = {
                "attempt_ids": [a.id for a in attempts],
                "item_keys": list(groups),
                "part_groups": list(groups.values()),
                "categories": [len(p) for p in groups.values()],
                "matrix": matrix,
                "policy": policy,
                "policy_id": exam.policy_id,
                "raw_scores": [a.raw_score for a in attempts],
                "max_scores": [a.max_score for a in attempts],
                "reference": "all submitted, fully reviewed attempts of this closed exam; population SD (ddof=0)",
            }
            snapshot["sha256"] = hashlib.sha256(
                json.dumps(snapshot, sort_keys=True, allow_nan=False).encode()
            ).hexdigest()
            run = CalibrationRun(
                exam_id=exam_id,
                model="PCM/mixed" if 2 in snapshot["categories"] else "Rasch-1PL",
                algorithm_version=ALGORITHM_VERSION,
                snapshot=snapshot,
            )
            session.add(run)
            await session.flush()
            run_id = run.id
            self.audit(
                session,
                actor,
                "calibration.start",
                exam_id=exam_id,
                run_id=run_id,
                sha256=snapshot["sha256"],
            )
        process = None
        try:
            # Limit BLAS worker threads and keep all bot credentials out of the worker environment.
            environment = {
                k: v for k, v in os.environ.items() if k in {"PATH", "SYSTEMROOT", "LANG", "TMPDIR"}
            }
            environment.update(
                OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1"
            )
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "quizbot.calibration_worker",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
            )
            output, _stderr = await asyncio.wait_for(
                process.communicate(json.dumps(snapshot, allow_nan=False).encode()),
                self.settings.calibration_timeout_seconds,
            )
            if process.returncode:
                result = {"error": "Calibration worker failed"}
            else:
                result = json.loads(output)
        except (TimeoutError, OSError, json.JSONDecodeError):
            result = {"error": "Calibration worker timed out or could not complete"}
        except asyncio.CancelledError:
            await self._fail_run(run_id, "Interrupted by shutdown")
            raise
        finally:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
        async with self.sessions.begin() as session:
            await self.locked_exam(session, exam_id)
            run = await session.get(CalibrationRun, run_id)
            if "error" in result:
                run.status = "failed"
                run.diagnostics = {"error": result["error"]}
            else:
                run.status = "ready" if result["stable"] else "unstable"
                run.diagnostics = result["diagnostics"]
                run.reference_mean = result["reference_mean"]
                run.reference_sd = result["reference_sd"]
                for j, key in enumerate(snapshot["item_keys"]):
                    session.add(
                        ItemParameter(
                            run_id=run_id,
                            item_key=key,
                            steps=result["steps"][j],
                            standard_errors=result["standard_errors"][j],
                        )
                    )
                for j, attempt_id in enumerate(snapshot["attempt_ids"]):
                    session.add(
                        StudentAbilityEstimate(
                            run_id=run_id,
                            attempt_id=attempt_id,
                            theta=result["theta"][j],
                            posterior_sd=result["posterior_sd"][j],
                        )
                    )
                    score = result["scores"][j]
                    session.add(
                        StandardizedScore(
                            run_id=run_id,
                            attempt_id=attempt_id,
                            z_score=score["z"],
                            t_score=score["t"],
                            grade=score["grade"],
                        )
                    )
            self.audit(session, actor, "calibration.finish", run_id=run_id, status=run.status)
            return {"run_id": run_id, "status": run.status, "diagnostics": run.diagnostics}

    async def _fail_run(self, run_id, reason):
        async with self.sessions.begin() as session:
            await session.execute(
                update(CalibrationRun)
                .where(CalibrationRun.id == run_id, CalibrationRun.status == "running")
                .values(status="failed", diagnostics={"error": reason})
            )

    async def recover_interrupted_runs(self):
        """Call at startup of the single polling instance after previous process stopped."""
        async with self.calibration_lease() as acquired:
            if not acquired:
                return
            async with self.sessions.begin() as session:
                await session.execute(
                    update(CalibrationRun)
                    .where(CalibrationRun.status == "running")
                    .values(
                        status="failed",
                        diagnostics={"error": "Process restarted before completion"},
                    )
                )

    async def release_results(self, actor: int, exam_id: int, run_id: int | None = None):
        self.admin(actor)
        if self.settings.grading_strategy == "simple":
            if run_id is not None:
                raise DomainError("Oddiy baholashda /release TEST_ID buyrug‘idan foydalaning.")
            return await self.release_simple_results(actor, exam_id)
        async with self.sessions.begin() as session:
            exam = await self.locked_exam(session, exam_id)
            if exam.results_released:
                raise DomainError("Natijalar allaqachon e’lon qilingan va o‘zgartirilmaydi.")
            await self._complete_cohort(session, exam)
            if await session.scalar(
                select(CalibrationRun.id)
                .where(CalibrationRun.exam_id == exam_id, CalibrationRun.status == "running")
                .limit(1)
            ):
                raise DomainError("Natijalarni e’lon qilishdan oldin kalibrlash tugashini kuting.")
            if not await session.scalar(
                select(Attempt.id).where(Attempt.exam_id == exam_id).limit(1)
            ):
                raise DomainError("Topshirilgan urinishlar yo‘q.")
            if run_id is not None:
                run = await session.get(CalibrationRun, run_id)
                if run is None or run.exam_id != exam_id or run.status != "ready":
                    raise DomainError(
                        "Faqat barqaror va joriy kalibrlash natijasini e’lon qilish mumkin."
                    )
            exam.results_released = True
            exam.released_run_id = run_id
            attempt_ids = await session.scalars(
                select(Attempt.id).where(Attempt.exam_id == exam_id, Attempt.status == "submitted")
            )
            session.add_all([ResultNotification(attempt_id=i) for i in attempt_ids])
            self.audit(
                session,
                actor,
                "results.release",
                exam_id=exam_id,
                run_id=run_id,
                raw_only=run_id is None,
            )
