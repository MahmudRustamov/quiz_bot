from sqlalchemy import delete, func, select

from quizbot.db.models import (
    AnswerKey,
    Attempt,
    Exam,
    ExamMaterial,
    GradingPolicy,
    Question,
    QuestionMaterial,
    QuestionOption,
    QuestionPart,
)
from quizbot.domain import DomainError
from quizbot.importing import ExamSpec, PolicySpec, QuestionSpec
from quizbot.services.base import Service


async def insert_question(session, exam_id: int, spec: QuestionSpec):
    q = Question(exam_id=exam_id, **spec.model_dump(exclude={"options", "parts", "material_keys"}))
    session.add(q)
    await session.flush()
    for position, key in enumerate(spec.material_keys):
        material = await session.scalar(
            select(ExamMaterial).where(ExamMaterial.exam_id == exam_id, ExamMaterial.key == key)
        )
        if material is None:
            raise DomainError("Savolga bog‘langan o‘qish matni topilmadi.")
        session.add(QuestionMaterial(question_id=q.id, material_id=material.id, position=position))
    session.add_all(
        [QuestionOption(question_id=q.id, label=k, text=v) for k, v in spec.options.items()]
    )
    for part in spec.parts:
        p = QuestionPart(
            question_id=q.id,
            **part.model_dump(exclude={"accepted", "ignore_case", "manual_review"}),
        )
        session.add(p)
        await session.flush()
        session.add(
            AnswerKey(
                part_id=p.id,
                accepted=part.accepted,
                ignore_case=part.ignore_case,
                manual_review=part.manual_review,
            )
        )


class ExamService(Service):
    async def import_exam(self, actor: int, spec: ExamSpec) -> Exam:
        self.admin(actor)
        async with self.sessions.begin() as session:
            policy = GradingPolicy(name=spec.title, config=spec.policy.model_dump())
            session.add(policy)
            await session.flush()
            exam = Exam(
                title=spec.title,
                subject=spec.subject,
                duration_minutes=spec.duration_minutes,
                policy_id=policy.id,
                simple_release_policy=spec.simple_release_policy,
                answer_review_enabled=spec.answer_review_enabled,
            )
            session.add(exam)
            await session.flush()
            session.add_all(
                [
                    ExamMaterial(exam_id=exam.id, **material.model_dump())
                    for material in spec.materials
                ]
            )
            await session.flush()
            for question in spec.questions:
                await insert_question(session, exam.id, question)
            self.audit(
                session, actor, "exam.import", exam_id=exam.id, questions=len(spec.questions)
            )
            return exam

    async def list_exams(
        self, actor: int, page: int = 0, *, administration: bool = False
    ) -> list[Exam]:
        if administration:
            self.admin(actor)
        async with self.sessions() as session:
            query = select(Exam).order_by(Exam.id.desc()).offset(max(0, page) * 8).limit(8)
            if not administration:
                query = query.where(Exam.published.is_(True))
            return list(await session.scalars(query))

    async def edit_exam(
        self,
        actor: int,
        exam_id: int,
        *,
        title: str | None = None,
        duration_minutes: int | None = None,
        policy: PolicySpec | None = None,
    ):
        self.admin(actor)
        async with self.sessions.begin() as session:
            exam = await self.locked_exam(session, exam_id)
            await self._editable(session, exam)
            if title is not None:
                if not 1 <= len(title.strip()) <= 200:
                    raise DomainError("Test nomi 1–200 belgi bo‘lsin.")
                exam.title = title.strip()
            if duration_minutes is not None:
                if not 1 <= duration_minutes <= 1440:
                    raise DomainError("Davomiylik 1–1440 daqiqa bo‘lsin.")
                exam.duration_minutes = duration_minutes
            if policy is not None:
                pcm = await session.scalar(
                    select(Question.id)
                    .where(Question.exam_id == exam_id, Question.pcm.is_(True))
                    .limit(1)
                )
                if pcm and not policy.pcm_assumptions_confirmed:
                    raise DomainError("PCM uchun asoslangan baholash siyosati kerak.")
                new = GradingPolicy(name=exam.title, config=policy.model_dump())
                session.add(new)
                await session.flush()
                exam.policy_id = new.id
            self.audit(session, actor, "exam.edit", exam_id=exam_id)

    async def put_question(self, actor: int, exam_id: int, spec: QuestionSpec):
        self.admin(actor)
        async with self.sessions.begin() as session:
            exam = await self.locked_exam(session, exam_id)
            await self._editable(session, exam)
            policy = await session.get(GradingPolicy, exam.policy_id)
            if spec.pcm and not policy.config.get("pcm_assumptions_confirmed"):
                raise DomainError("PCM uchun asoslangan baholash siyosati kerak.")
            await session.execute(
                delete(Question).where(Question.exam_id == exam_id, Question.number == spec.number)
            )
            await insert_question(session, exam_id, spec)
            self.audit(session, actor, "question.put", exam_id=exam_id, number=spec.number)

    @staticmethod
    async def _editable(session, exam):
        count = await session.scalar(
            select(func.count()).select_from(Attempt).where(Attempt.exam_id == exam.id)
        )
        if exam.published or count:
            raise DomainError(
                "Tahrirlash uchun test e’lon qilinmagan va hali boshlanmagan bo‘lishi kerak. Yangi test nusxasini import qiling."
            )

    async def set_published(self, actor: int, exam_id: int, published: bool):
        self.admin(actor)
        async with self.sessions.begin() as session:
            exam = await self.locked_exam(session, exam_id)
            if published:
                questions = list(
                    await session.scalars(select(Question).where(Question.exam_id == exam_id))
                )
                if not questions or any(q.needs_review for q in questions):
                    raise DomainError("Savollar to‘liq emas yoki manba tekshiruvi kutilmoqda.")
                if exam.closed:
                    raise DomainError("Yopilgan testga yangi qatnashchilar qo‘shib bo‘lmaydi.")
            exam.published = published
            self.audit(
                session, actor, "exam.publish" if published else "exam.unpublish", exam_id=exam_id
            )

    async def close_exam(self, actor: int, exam_id: int):
        self.admin(actor)
        async with self.sessions.begin() as session:
            exam = await self.locked_exam(session, exam_id)
            exam.closed = True
            self.audit(session, actor, "exam.close", exam_id=exam_id)
