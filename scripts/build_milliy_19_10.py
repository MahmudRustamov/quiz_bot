"""Build a self-contained import from reviewed PDF transcription and the supplied key.

No PDF/OCR dependency is needed to rebuild. Source questions and reading passages
remain separate from the transcribed answer key for straightforward review.
"""

import hashlib
import json
from pathlib import Path

from quizbot.importing import ExamSpec

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "exams" / "source"


def build() -> ExamSpec:
    content = json.loads((SOURCE / "19-10-questions.json").read_text(encoding="utf-8"))
    key = json.loads((SOURCE / "19-10-answer-key.json").read_text(encoding="utf-8"))
    materials = [
        {
            "key": name,
            "title": title,
            "text": (SOURCE / f"{name}.txt").read_text(encoding="utf-8").strip(),
            "source_pages": pages,
        }
        for name, title, pages in [
            ("teleskop", "TELESKOP — 18–22-savollar uchun matn", [5]),
            ("myunodi", "Myunodi haqidagi parcha — 23–27-savollar uchun matn", [7, 8, 9]),
            ("gazal", "G‘azal — 28–32-savollar uchun matn", [11]),
        ]
    ]
    questions = []
    for source in content["questions"]:
        number = source["number"]
        question = {k: v for k, v in source.items() if k not in {"pages", "part_prompts"}}
        rubric = {
            "source_pdf": "19.10_MS_MOCK_TEST_tahrirlangan.pdf",
            "source_pages": source["pages"],
            "answer_key_source": "User-supplied TEST JAVOBLARI image",
            "raw_scoring_policy": "Simplified practice policy: one point per answer element, not an official weight",
            "grading_policy": "Exact accepted variants after NFKC/whitespace normalization; ignore capitalization. No semantic matching.",
        }
        if number <= 35:
            parts = [{"accepted": [key["multiple_choice_and_matching"][str(number)]]}]
        elif number <= 39:
            accepted = [key["written"][str(number)]]
            if number == 37:
                accepted = ["; → :", ";→:", "; -> :", ";->:"]
                rubric["format_variants"] = (
                    "Spaces around the arrow and ASCII -> are explicitly accepted representations of the supplied semicolon-to-colon correction."
                )
            elif number == 39:
                accepted = [f"o{mark}sha paytda men 9-sinf edim" for mark in ["‘", "'", "ʻ", "’"]]
                rubric["format_variants"] = (
                    "Only the four explicitly listed apostrophe variants are accepted; no words are changed or omitted."
                )
            parts = [{"accepted": accepted}]
        else:
            parts = []
            for label in ["A", "B"]:
                value = key["multipart"][str(number)][label]
                accepted = value if isinstance(value, list) else [value]
                if number == 44 and label == "B":
                    accepted = [*accepted, "yor – oydurur", "yor — oydurur", "yor - oydurur"]
                    rubric["format_variants"] = (
                        "The supplied key explicitly lists Yor oydurur / yoroydurur. The dash forms reproduce the first line in the supplied PDF."
                    )
                parts.append(
                    {"label": label, "prompt": source["part_prompts"][label], "accepted": accepted}
                )
        if number in {3, 4, 7, 8, 36}:
            rubric["layout_note"] = (
                "Diagram labels and connections transcribed as text; no visual interpretation is needed beyond the included labels."
            )
        if number == 40:
            rubric["source_note"] = (
                "PDF page 14 labels both parts 'a)'. The second is mapped to B, consistently with the supplied A/B answer key."
            )
        if number == 43:
            rubric["layout_note"] = (
                "The PDF underlines dahr and shahr; these words are explicitly identified in the student-facing statement."
            )
        question.update(parts=parts, rubric=rubric, needs_review=False)
        questions.append(question)
    return ExamSpec(
        title=content["title"],
        subject="Ona tili va adabiyot",
        duration_minutes=content["duration_minutes"],
        materials=materials,
        questions=questions,
    )


def main():
    spec = build()
    output = ROOT / "exams" / "19-10-ms-mock.json"
    payload = json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    output.write_text(payload, encoding="utf-8")
    print(
        f"{output.name}: {len(spec.questions)} questions, {sum(len(q.parts) for q in spec.questions)} elements, {len(spec.materials)} reading passages"
    )
    print("Import SHA-256:", hashlib.sha256(payload.encode()).hexdigest())


if __name__ == "__main__":
    main()
