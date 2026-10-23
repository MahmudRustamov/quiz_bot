from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    first_name: Mapped[str | None] = mapped_column(String(75))
    last_name: Mapped[str | None] = mapped_column(String(75))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GradingPolicy(Base):
    __tablename__ = "grading_policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    config: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Exam(Base):
    __tablename__ = "exams"
    __table_args__ = (CheckConstraint("duration_minutes > 0"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str | None] = mapped_column(String(200))
    simple_release_policy: Mapped[str | None] = mapped_column(String(20))
    simple_results_released: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    answer_review_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, default=180)
    policy_id: Mapped[int] = mapped_column(ForeignKey("grading_policies.id", ondelete="RESTRICT"))
    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    results_released: Mapped[bool] = mapped_column(Boolean, default=False)
    released_run_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "calibration_runs.id", use_alter=True, name="fk_exam_released_run", ondelete="RESTRICT"
        )
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("exam_id", "number"), CheckConstraint("number > 0"))
    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="RESTRICT"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    statement: Mapped[str] = mapped_column(Text)
    image_file_id: Mapped[str | None] = mapped_column(String(500))
    rubric: Mapped[dict] = mapped_column(JSON, default=dict)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    pcm: Mapped[bool] = mapped_column(Boolean, default=False)


class ExamMaterial(Base):
    __tablename__ = "exam_materials"
    __table_args__ = (UniqueConstraint("exam_id", "key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="RESTRICT"), index=True)
    key: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    source_pages: Mapped[list] = mapped_column(JSON, default=list)


class QuestionMaterial(Base):
    __tablename__ = "question_materials"
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    material_id: Mapped[int] = mapped_column(
        ForeignKey("exam_materials.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)


class QuestionOption(Base):
    __tablename__ = "question_options"
    __table_args__ = (UniqueConstraint("question_id", "label"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)


class QuestionPart(Base):
    """Every question has one or more scored elements; multipart shares a parent."""

    __tablename__ = "question_parts"
    __table_args__ = (UniqueConstraint("question_id", "label"), CheckConstraint("weight > 0"))
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(10), default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    weight: Mapped[float] = mapped_column(Float, default=1.0)


class AnswerKey(Base):
    __tablename__ = "answer_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(
        ForeignKey("question_parts.id", ondelete="CASCADE"), unique=True
    )
    accepted: Mapped[list] = mapped_column(JSON, default=list)
    ignore_case: Mapped[bool] = mapped_column(Boolean, default=True)
    manual_review: Mapped[bool] = mapped_column(Boolean, default=False)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("exam_id", "user_id"),
        CheckConstraint("status IN ('in_progress', 'submitted')"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    simple_released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_score: Mapped[float | None] = mapped_column(Float)
    max_score: Mapped[float | None] = mapped_column(Float)


class StudentResponse(Base):
    __tablename__ = "student_responses"
    __table_args__ = (UniqueConstraint("attempt_id", "part_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("attempts.id", ondelete="RESTRICT"), index=True
    )
    part_id: Mapped[int] = mapped_column(
        ForeignKey("question_parts.id", ondelete="RESTRICT"), index=True
    )
    answer: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class GradingResult(Base):
    __tablename__ = "grading_results"
    __table_args__ = (
        UniqueConstraint("attempt_id", "part_id"),
        CheckConstraint("category IS NULL OR category IN (0, 1)"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("attempts.id", ondelete="RESTRICT"), index=True
    )
    part_id: Mapped[int] = mapped_column(ForeignKey("question_parts.id", ondelete="RESTRICT"))
    category: Mapped[int | None] = mapped_column(Integer)
    raw_points: Mapped[float | None] = mapped_column(Float)
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewer_id: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str] = mapped_column(Text, default="")


class CalibrationRun(Base):
    __tablename__ = "calibration_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    model: Mapped[str] = mapped_column(String(30))
    algorithm_version: Mapped[str] = mapped_column(String(50))
    snapshot: Mapped[dict] = mapped_column(JSON)
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict)
    reference_mean: Mapped[float | None] = mapped_column(Float)
    reference_sd: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ItemParameter(Base):
    __tablename__ = "item_parameters"
    __table_args__ = (UniqueConstraint("run_id", "item_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("calibration_runs.id", ondelete="RESTRICT"), index=True
    )
    item_key: Mapped[str] = mapped_column(String(50))
    steps: Mapped[list] = mapped_column(JSON)
    standard_errors: Mapped[list] = mapped_column(JSON)


class StudentAbilityEstimate(Base):
    __tablename__ = "student_ability_estimates"
    __table_args__ = (UniqueConstraint("run_id", "attempt_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("calibration_runs.id", ondelete="RESTRICT"), index=True
    )
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("attempts.id", ondelete="RESTRICT"), index=True
    )
    theta: Mapped[float] = mapped_column(Float)
    posterior_sd: Mapped[float] = mapped_column(Float)


class StandardizedScore(Base):
    __tablename__ = "standardized_scores"
    __table_args__ = (UniqueConstraint("run_id", "attempt_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("calibration_runs.id", ondelete="RESTRICT"), index=True
    )
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("attempts.id", ondelete="RESTRICT"), index=True
    )
    z_score: Mapped[float] = mapped_column(Float)
    t_score: Mapped[float] = mapped_column(Float)
    grade: Mapped[str] = mapped_column(String(20))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FSMRecord(Base):
    __tablename__ = "fsm_records"
    key: Mapped[str] = mapped_column(String(250), primary_key=True)
    state: Mapped[str | None] = mapped_column(String(250))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class ResultNotification(Base):
    __tablename__ = "result_notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("attempts.id", ondelete="RESTRICT"), unique=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tries: Mapped[int] = mapped_column(Integer, default=0)
    next_retry: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


Index("ix_attempts_exam_status", Attempt.exam_id, Attempt.status)
