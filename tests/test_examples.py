from pathlib import Path

from quizbot.importing import parse_import

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_initial_structure_is_unverified_and_complete():
    exam = parse_import((EXAMPLES / "milliy-44.unverified.json").read_bytes(), "initial.json")
    assert len(exam.questions) == 44
    assert sum(len(q.parts) for q in exam.questions) == 49
    assert all(q.needs_review for q in exam.questions)
    assert all(not p.accepted for q in exam.questions for p in q.parts)


def test_json_csv_equivalence():
    json = parse_import((EXAMPLES / "demo-exam.json").read_bytes(), "demo.json")
    csv = parse_import((EXAMPLES / "demo-exam.csv").read_bytes(), "demo.csv")
    assert json == csv
