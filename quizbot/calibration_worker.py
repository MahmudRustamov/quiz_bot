"""Isolated CPU worker: no credentials, database access, or Telegram interaction."""

import json
import sys

import numpy as np
import scipy

from quizbot.psychometrics.models import calibrate
from quizbot.psychometrics.standardize import assign_grade, reference_statistics, standardize


def compute(snapshot: dict) -> dict:
    policy = snapshot["policy"]
    matrix = np.array(
        [[np.nan if x is None else x for x in row] for row in snapshot["matrix"]], dtype=float
    )
    fit = calibrate(
        matrix,
        snapshot["categories"],
        missing_policy=policy["missing_policy"],
        min_students=policy["min_students"],
        min_item_responses=policy["min_item_responses"],
        min_category_count=policy["min_category_count"],
    )
    mean, sd = reference_statistics(fit.theta)
    standardized = [standardize(float(t), mean, sd) for t in fit.theta]
    fit.diagnostics["libraries"] = {"numpy": np.__version__, "scipy": scipy.__version__}
    return {
        "stable": fit.stable,
        "steps": [s.tolist() for s in fit.steps],
        "standard_errors": [
            [float(x) if np.isfinite(x) else None for x in s] for s in fit.standard_errors
        ],
        "theta": fit.theta.tolist(),
        "posterior_sd": fit.posterior_sd.tolist(),
        "reference_mean": mean,
        "reference_sd": sd,
        "scores": [
            {"z": z, "t": t, "grade": assign_grade(t, policy["boundaries"])}
            for z, t in standardized
        ],
        "diagnostics": fit.diagnostics,
    }


if __name__ == "__main__":
    try:
        output = compute(json.load(sys.stdin))
    except (ValueError, np.linalg.LinAlgError) as exc:
        output = {"error": str(exc)}
    json.dump(output, sys.stdout, allow_nan=False)
