import unicodedata
from dataclasses import dataclass


def normalize_answer(value: str, ignore_case: bool = True) -> str:
    value = " ".join(unicodedata.normalize("NFKC", value).split())
    return value.casefold() if ignore_case else value


@dataclass(frozen=True)
class RawGrade:
    category: int | None
    points: float | None
    pending: bool


def grade_answer(
    answer: str | None,
    accepted: list[str],
    *,
    weight: float = 1.0,
    ignore_case: bool = True,
    manual_review: bool = False,
) -> RawGrade:
    """Exact normalized comparison only. Blank/unanswered always earns zero."""
    if answer is None or not normalize_answer(answer):
        return RawGrade(0, 0.0, False)
    if manual_review:
        return RawGrade(None, None, True)
    if not accepted:
        raise ValueError("An automatic grading key cannot be empty")
    category = int(
        normalize_answer(answer, ignore_case)
        in {normalize_answer(a, ignore_case) for a in accepted}
    )
    return RawGrade(category, category * weight, False)
