"""Regenerate import examples and the unverified 44-parent/49-element template."""

import csv
import json
from pathlib import Path

from quizbot.importing import ExamSpec, PolicySpec, QuestionSpec

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "examples"
OUTPUT.mkdir(exist_ok=True)


def write(name, data):
    (OUTPUT / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


questions = []
for number in range(1, 45):
    kind = (
        "mcq"
        if number <= 32
        else "matching"
        if number <= 35
        else "written"
        if number <= 39
        else "multipart"
    )
    questions.append(
        {
            "number": number,
            "kind": kind,
            "statement": "",
            "options": {},
            "needs_review": True,
            "rubric": {
                "source_status": "PDF and answer-key image not provided; verify all content before publishing",
                "weight_status": "1 point per element is a configurable simplified practice policy, not an official weight",
            },
            "parts": [
                {"label": label, "weight": 1.0, "accepted": []}
                for label in (["A", "B"] if kind == "multipart" else [""])
            ],
        }
    )
template = ExamSpec(
    title="Ona tili va adabiyot — manba tekshiruvi kutilmoqda",
    duration_minutes=180,
    questions=questions,
)
write("milliy-44.unverified.json", template.model_dump(mode="json"))

demo = ExamSpec(
    title="Dastur sinovi — namuna (haqiqiy imtihon emas)",
    duration_minutes=15,
    questions=[
        {
            "number": 1,
            "kind": "mcq",
            "statement": "Dastur sinovi: 2 + 2 = ?",
            "options": {"A": "4", "B": "5"},
            "parts": [{"accepted": ["A"]}],
        },
        {
            "number": 2,
            "kind": "matching",
            "statement": "Dastur sinovi: «bir» soniga mos variantni tanlang.",
            "options": {"A": "1", "B": "2", "C": "3", "D": "4", "E": "5", "F": "6"},
            "parts": [{"accepted": ["A"]}],
        },
        {
            "number": 3,
            "kind": "written",
            "statement": "Dastur sinovi: «kitob» so‘zini yozing.",
            "parts": [{"accepted": ["kitob"], "ignore_case": True}],
        },
        {
            "number": 4,
            "kind": "multipart",
            "statement": "Dastur sinovi: A qismda «bir», B qismda «ikki» deb yozing.",
            "rubric": {
                "A": "Exact accepted variant; one point",
                "B": "Exact accepted variant; one point",
            },
            "parts": [
                {"label": "A", "accepted": ["bir", "1"]},
                {"label": "B", "accepted": ["ikki", "2"]},
            ],
        },
    ],
)
write("demo-exam.json", demo.model_dump(mode="json"))
write("policy.json", PolicySpec().model_dump())
write("question.json", demo.questions[0].model_dump(mode="json"))
write("exam.schema.json", ExamSpec.model_json_schema())
write("question.schema.json", QuestionSpec.model_json_schema())
write("policy.schema.json", PolicySpec.model_json_schema())
with (OUTPUT / "demo-exam.csv").open("w", encoding="utf-8", newline="") as file:
    fields = ["title", "duration_minutes", "policy", *demo.questions[0].model_dump().keys()]
    writer = csv.DictWriter(file, fieldnames=fields)
    writer.writeheader()
    for question in demo.questions:
        row = question.model_dump(mode="json")
        for key in ("options", "rubric", "parts", "needs_review", "pcm", "material_keys"):
            row[key] = json.dumps(row[key], ensure_ascii=False)
        writer.writerow(
            {
                "title": demo.title,
                "duration_minutes": demo.duration_minutes,
                "policy": json.dumps(demo.policy.model_dump()),
                **row,
            }
        )
