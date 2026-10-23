import json
from pathlib import Path

import pytest

from quizbot.bot.materials import send_materials, split_material
from quizbot.grading import grade_answer
from quizbot.importing import ExamSpec, parse_import

ROOT = Path(__file__).resolve().parents[1]
EXAM = ROOT / "exams" / "19-10-ms-mock.json"


def load_exam():
    return parse_import(EXAM.read_bytes(), EXAM.name)


def test_real_exam_structure_and_supplied_key():
    exam = load_exam()
    assert [q.number for q in exam.questions] == list(range(1, 45))
    assert [q.kind for q in exam.questions[:32]] == ["mcq"] * 32
    assert [q.kind for q in exam.questions[32:35]] == ["matching"] * 3
    assert [q.kind for q in exam.questions[35:39]] == ["written"] * 4
    assert [q.kind for q in exam.questions[39:]] == ["multipart"] * 5
    assert sum(len(q.parts) for q in exam.questions) == 49
    assert all(not q.needs_review and not q.pcm for q in exam.questions)
    expected = "AAACDBCCDBAADD BACBBACCBACBAADCBDCAF".replace(" ", "")
    assert len(expected) == 35
    assert "".join(q.parts[0].accepted[0] for q in exam.questions[:35]) == expected
    assert exam.questions[35].parts[0].accepted == ["iziga tushmoq"]
    assert exam.questions[39].parts[1].accepted == ["badani iborat"]
    assert exam.questions[42].parts[0].accepted == ["r"]
    assert exam.questions[43].parts[0].accepted == ["tuyuq"]


def test_complete_shared_passages_are_linked_to_all_applicable_questions():
    exam = load_exam()
    materials = {m.key: m for m in exam.materials}
    assert set(materials) == {"teleskop", "myunodi", "gazal"}
    assert len(materials["myunodi"].text) > 9000
    assert all(f"[{i}]" in materials["myunodi"].text for i in range(1, 6))
    assert all(
        f"\n{roman}\n" in "\n" + materials["teleskop"].text
        for roman in ["I", "II", "III", "IV", "V"]
    )
    assert len([line for line in materials["gazal"].text.splitlines() if line.strip()]) == 14
    assert len(materials["gazal"].text.split("\n\n")) == 7
    assert materials["gazal"].text.count("ustina") == 8
    assert all(q.material_keys == ["teleskop"] for q in exam.questions[17:22])
    assert all(q.material_keys == ["myunodi"] for q in exam.questions[22:27])
    assert all(q.material_keys == ["gazal"] for q in exam.questions[27:32])


def test_only_explicit_written_variants_are_accepted():
    exam = load_exam()
    q37 = exam.questions[36].parts[0]
    for answer in ["; → :", ";→:", "; -> :", ";->:"]:
        assert grade_answer(answer, q37.accepted).category == 1
    assert grade_answer(": → ;", q37.accepted).category == 0
    q39 = exam.questions[38].parts[0]
    assert grade_answer("o'sha paytda men 9-sinf edim", q39.accepted).category == 1
    assert grade_answer("o‘sha paytda men 9-sinfda edim", q39.accepted).category == 0
    q44b = exam.questions[43].parts[1]
    for answer in ["Yor oydurur", "yoroydurur", "yor – oydurur"]:
        assert grade_answer(answer, q44b.accepted).category == 1


def test_material_chunks_preserve_every_word_and_fit_telegram():
    for material in load_exam().materials:
        text = material.text
        chunks = split_material(text)
        assert all(0 < len(chunk) <= 3500 for chunk in chunks)
        assert " ".join(" ".join(chunks).split()) == " ".join(text.split())
    assert [len(c) for c in split_material("x" * 8000)] == [3500, 3500, 1000]


async def test_material_delivery_includes_heading_and_full_content():
    class Message:
        def __init__(self):
            self.sent = []

        async def answer(self, text):
            self.sent.append(text)

    message = Message()
    material = load_exam().materials[1]
    await send_materials(message, [material.model_dump()])
    assert len(message.sent) >= 3
    assert message.sent[0].startswith("📖")
    assert all(len(text) <= 3500 for text in message.sent)
    assert "xayolparast edim" in message.sent[-1]


def test_material_references_are_validated():
    with pytest.raises(ValueError, match="undefined reading material"):
        ExamSpec(
            title="x",
            questions=[
                {
                    "number": 1,
                    "kind": "written",
                    "statement": "x",
                    "material_keys": ["missing"],
                    "parts": [{"accepted": ["x"]}],
                }
            ],
        )


def test_import_matches_reviewed_source_questions():
    source = json.loads((ROOT / "exams/source/19-10-questions.json").read_text())
    exam = load_exam()
    for original, imported in zip(source["questions"], exam.questions, strict=True):
        assert original["statement"] == imported.statement
        assert original.get("options", {}) == imported.options
        assert original["pages"] == imported.rubric["source_pages"]


@pytest.mark.postgres
async def test_full_real_exam_import_and_all_49_answers(platform):
    spec = load_exam()
    exam = await platform.import_exam(999, spec)
    await platform.set_published(999, exam.id, True)
    await platform.register(123, "Sinov O‘quvchi")
    attempt = await platform.start_attempt(123, exam.id)
    expected_parts = [(q, p) for q in spec.questions for p in q.parts]
    for index, (question, part) in enumerate(expected_parts):
        view = await platform.question_view(123, attempt.id, index)
        assert view["number"] == question.number
        assert view["label"] == part.label
        assert [m["key"] for m in view["materials"]] == question.material_keys
        assert "accepted" not in view
        await platform.save_answer(123, attempt.id, view["part_id"], part.accepted[0])
    submitted = await platform.submit_attempt(123, attempt.id)
    assert submitted.raw_score == submitted.max_score == 49
