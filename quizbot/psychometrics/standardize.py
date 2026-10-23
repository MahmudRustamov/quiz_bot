import math

import numpy as np

from quizbot.importing import DEFAULT_BOUNDARIES


def reference_statistics(theta: np.ndarray) -> tuple[float, float]:
    values = np.asarray(theta, dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.all(np.isfinite(values)):
        raise ValueError("Reference cohort requires at least two finite abilities")
    mean, sd = float(values.mean()), float(values.std(ddof=0))
    if sd < 1e-8:
        raise ValueError("Reference cohort has zero ability variance")
    return mean, sd


def standardize(theta: float, mean: float, sd: float) -> tuple[float, float]:
    if not all(math.isfinite(v) for v in (theta, mean, sd)) or sd < 1e-8:
        raise ValueError("Finite abilities and positive reference SD are required")
    z = (theta - mean) / sd
    return z, 50.0 + 10.0 * z


def assign_grade(t_score: float, boundaries: dict[str, float] | None = None) -> str:
    if not math.isfinite(t_score):
        raise ValueError("T-score must be finite")
    for label, minimum in sorted(
        (boundaries or DEFAULT_BOUNDARIES).items(), key=lambda pair: pair[1], reverse=True
    ):
        if t_score >= minimum:
            return label
    return "Below C"
