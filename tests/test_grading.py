import pytest

from quizbot.grading import grade_answer, normalize_answer
from quizbot.importing import ExamSpec, QuestionSpec, parse_import


@pytest.mark.parametrize(
    "kind,key,answer,expected",
    [("mcq", "A", "A", 1), ("mcq", "B", "C", 0), ("matching", "F", "f", 1)],
)
def test_choices(kind, key, answer, expected):
    assert grade_answer(answer, [key]).category == expected


def test_unicode_whitespace_and_case():
    assert normalize_answer("  Ａｌｉ\u00a0 \n Vali  ") == "ali vali"
    assert grade_answer("  Adabiyot  ", ["adabiyot"]).category == 1
    assert grade_answer("Adabiyot", ["adabiyot"], ignore_case=False).category == 0
    assert grade_answer("kitoblar", ["kitob"]).category == 0


def test_multipart_weights_and_missing():
    parts = [grade_answer("A", ["A"], weight=2), grade_answer("C", ["B"], weight=3)]
    assert sum(p.points for p in parts) == 2
    assert sum(p.category for p in parts) == 1
    assert grade_answer(None, ["x"], manual_review=True).points == 0
    assert grade_answer("x", [], manual_review=True).pending
    with pytest.raises(ValueError):
        grade_answer("x", [])


def test_import_rejects_invented_empty_verified_content():
    with pytest.raises(ValueError):
        QuestionSpec(number=1, kind="written", parts=[{"accepted": ["x"]}])
    draft = QuestionSpec(number=1, kind="written", needs_review=True, parts=[{}])
    assert draft.needs_review


def test_import_validation():
    with pytest.raises(ValueError):
        parse_import(b'{"title":"x","malicious":1}', "x.json")
    with pytest.raises(ValueError):
        parse_import(b"x" * 2_000_001, "x.json")
    with pytest.raises(ValueError):
        ExamSpec(title="x", policy={"boundaries": {"A+": 0}})


def test_pcm_needs_explicit_review():
    with pytest.raises(ValueError, match="PCM requires"):
        ExamSpec(
            title="x",
            questions=[
                {
                    "number": 1,
                    "kind": "multipart",
                    "pcm": True,
                    "needs_review": True,
                    "parts": [{"label": "A"}, {"label": "B"}],
                }
            ],
        )
