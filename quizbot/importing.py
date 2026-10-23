"""Strict JSON and CSV imports. Uncertain source text must be explicitly marked."""

import csv
import io
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quizbot.domain import QuestionKind

DEFAULT_BOUNDARIES = {"A+": 70.0, "A": 65.0, "B+": 60.0, "B": 55.0, "C+": 50.0, "C": 46.0}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PolicySpec(StrictModel):
    boundaries: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_BOUNDARIES))
    missing_policy: Literal["zero", "omit"] = "zero"
    min_students: int = Field(default=100, ge=30, le=100000)
    min_item_responses: int = Field(default=30, ge=10)
    min_category_count: int = Field(default=5, ge=3)
    pcm_assumptions_confirmed: bool = False
    assumptions_note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_boundaries(self):
        if set(self.boundaries) != set(DEFAULT_BOUNDARIES):
            raise ValueError("Grade labels must be A+, A, B+, B, C+, C")
        values = [self.boundaries[k] for k in DEFAULT_BOUNDARIES]
        if any(a <= b for a, b in zip(values, values[1:], strict=False)):
            raise ValueError("Grade thresholds must strictly descend")
        if self.pcm_assumptions_confirmed and not self.assumptions_note.strip():
            raise ValueError("Document the PCM design/assumption review")
        return self


class PartSpec(StrictModel):
    label: str = Field(default="", max_length=10)
    prompt: str = Field(default="", max_length=4000)
    weight: float = Field(default=1.0, gt=0, le=100)
    accepted: list[str] = Field(default_factory=list, max_length=100)
    ignore_case: bool = True
    manual_review: bool = False

    @model_validator(mode="after")
    def answers_not_blank(self):
        if any(not a.strip() or len(a) > 2000 for a in self.accepted):
            raise ValueError("Accepted answers must be nonempty and at most 2000 characters")
        return self


class QuestionSpec(StrictModel):
    number: int = Field(gt=0, le=500)
    kind: QuestionKind
    statement: str = Field(default="", max_length=3000)
    options: dict[str, str] = Field(default_factory=dict, max_length=12)
    image_file_id: str | None = Field(default=None, max_length=500)
    material_keys: list[str] = Field(default_factory=list, max_length=10)
    rubric: dict = Field(default_factory=dict)
    needs_review: bool = False
    pcm: bool = False
    parts: list[PartSpec] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def valid_structure(self):
        multipart = self.kind == QuestionKind.MULTIPART
        if len(self.parts) != (2 if multipart else 1):
            raise ValueError("Multipart requires two parts; other questions require one")
        if len({p.label for p in self.parts}) != len(self.parts):
            raise ValueError("Part labels must be unique")
        if len(set(self.material_keys)) != len(self.material_keys):
            raise ValueError("Reading material keys must be unique per question")
        if multipart and any(not p.label for p in self.parts):
            raise ValueError("Multipart labels are required")
        if self.pcm and not multipart:
            raise ValueError("PCM is optional and only supported for two-part items")
        if any(
            not k.isascii() or not k.isalpha() or not k.isupper() or len(k) > 2
            for k in self.options
        ):
            raise ValueError("Option labels must be uppercase ASCII letters")
        if any(not v.strip() or len(v) > 500 for v in self.options.values()):
            raise ValueError("Option text must contain 1..500 characters")
        if len(self.statement) + sum(len(k) + len(v) + 4 for k, v in self.options.items()) > 3400:
            raise ValueError("Question and options exceed Telegram message budget; use an image")
        if (
            len(self.statement)
            + sum(len(k) + len(v) + 4 for k, v in self.options.items())
            + max(len(p.prompt) for p in self.parts)
            > 3500
        ):
            raise ValueError("Question, part prompt, and options exceed Telegram message budget")
        if not self.needs_review:
            if not self.statement.strip() and not self.image_file_id:
                raise ValueError("A verified question needs a statement or image")
            for part in self.parts:
                if not part.accepted and not part.manual_review:
                    raise ValueError("A verified question needs an answer key or manual rubric")
            if self.kind in (QuestionKind.MCQ, QuestionKind.MATCHING):
                if len(self.options) < 2:
                    raise ValueError("Choice/matching items need at least two options")
                if (
                    len(self.parts[0].accepted) != 1
                    or self.parts[0].accepted[0] not in self.options
                ):
                    raise ValueError("Choice/matching key must identify exactly one option")
                if self.parts[0].manual_review:
                    raise ValueError("Choice/matching items must be automatically graded")
        return self


class MaterialSpec(StrictModel):
    key: str = Field(pattern=r"^[a-z0-9_-]{1,60}$")
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=50000)
    source_pages: list[int] = Field(default_factory=list, max_length=100)


class ExamSpec(StrictModel):
    schema_version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=200)
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    simple_release_policy: Literal["immediate", "manual"] | None = None
    answer_review_enabled: bool = True
    duration_minutes: int = Field(default=180, gt=0, le=1440)
    policy: PolicySpec = Field(default_factory=PolicySpec)
    materials: list[MaterialSpec] = Field(default_factory=list, max_length=100)
    questions: list[QuestionSpec] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def unique_numbers(self):
        numbers = [q.number for q in self.questions]
        if len(set(numbers)) != len(numbers):
            raise ValueError("Question numbers must be unique")
        material_keys = [m.key for m in self.materials]
        if len(set(material_keys)) != len(material_keys):
            raise ValueError("Reading material keys must be unique")
        if any(set(q.material_keys) - set(material_keys) for q in self.questions):
            raise ValueError("A question references an undefined reading material")
        if any(q.pcm for q in self.questions) and not self.policy.pcm_assumptions_confirmed:
            raise ValueError("PCM requires an explicit documented design review")
        return self


def parse_import(payload: bytes, filename: str) -> ExamSpec:
    if len(payload) > 2_000_000:
        raise ValueError("Import exceeds 2 MB")
    text = payload.decode("utf-8-sig")
    if filename.lower().endswith(".json"):
        return ExamSpec.model_validate_json(text)
    if not filename.lower().endswith(".csv"):
        raise ValueError("Only UTF-8 JSON and CSV are supported")
    # A CSV row is one parent question; structured fields use JSON inside the cell.
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or len(rows) > 500:
        raise ValueError("CSV must have 1..500 question rows")
    header = {
        "title",
        "duration_minutes",
        "policy",
        "number",
        "kind",
        "statement",
        "options",
        "parts",
        "rubric",
        "needs_review",
        "pcm",
        "image_file_id",
        "material_keys",
        "materials",
        "subject",
        "simple_release_policy",
        "answer_review_enabled",
    }
    if set(rows[0]) - header:
        raise ValueError("Unknown CSV columns")
    questions = []
    for row in rows:
        if (
            row.get("title") != rows[0].get("title")
            or row.get("duration_minutes") != rows[0].get("duration_minutes")
            or row.get("policy", "") != rows[0].get("policy", "")
            or row.get("materials", "") != rows[0].get("materials", "")
            or any(
                row.get(k, "") != rows[0].get(k, "")
                for k in ("subject", "simple_release_policy", "answer_review_enabled")
            )
        ):
            raise ValueError("CSV exam metadata must be identical on every row")
        q = {
            k: v
            for k, v in row.items()
            if k
            not in {
                "title",
                "duration_minutes",
                "policy",
                "materials",
                "subject",
                "simple_release_policy",
                "answer_review_enabled",
            }
            and v not in (None, "")
        }
        for key in ("options", "parts", "rubric", "needs_review", "pcm", "material_keys"):
            if key in q:
                q[key] = json.loads(q[key])
        questions.append(q)
    return ExamSpec.model_validate(
        {
            "title": rows[0]["title"],
            "duration_minutes": rows[0]["duration_minutes"],
            "policy": json.loads(rows[0].get("policy") or "{}"),
            "materials": json.loads(rows[0].get("materials") or "[]"),
            "subject": rows[0].get("subject") or None,
            "simple_release_policy": rows[0].get("simple_release_policy") or None,
            "answer_review_enabled": json.loads(rows[0].get("answer_review_enabled") or "true"),
            "questions": questions,
        }
    )
