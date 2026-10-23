import numpy as np
import pytest

from quizbot.domain import CalibrationError
from quizbot.psychometrics.models import (
    calibrate,
    estimate_abilities,
    pcm_probabilities,
    rasch_probability,
)
from quizbot.psychometrics.standardize import assign_grade, reference_statistics, standardize


def binary_data(n=1200, seed=19):
    rng = np.random.default_rng(seed)
    difficulty = np.linspace(-1.5, 1.5, 12)
    theta = rng.normal(size=n)
    return (
        (rng.random((n, len(difficulty))) < rasch_probability(theta[:, None], difficulty)).astype(
            float
        ),
        theta,
        difficulty,
    )


@pytest.fixture(scope="module")
def fitted():
    matrix, theta, difficulty = binary_data()
    return matrix, theta, difficulty, calibrate(matrix)


def test_rasch_probability():
    assert rasch_probability(0, 0) == 0.5
    assert rasch_probability(2, -1) > rasch_probability(1, -1)
    assert rasch_probability(0, 1000) == 0


def test_item_parameter_recovery(fitted):
    matrix, theta, difficulty, fit = fitted
    assert fit.stable, fit.diagnostics
    estimated = np.array([s[0] for s in fit.steps])
    assert np.sqrt(np.mean((estimated - difficulty) ** 2)) < 0.16
    assert np.corrcoef(theta, fit.theta)[0, 1] > 0.8
    assert np.all(np.array(fit.standard_errors) > 0)
    assert np.all(fit.posterior_sd > 0)


def test_calibration_reproducibility(fitted):
    matrix, _, _, fit = fitted
    second = calibrate(matrix)
    np.testing.assert_allclose(second.steps, fit.steps, atol=1e-10)
    np.testing.assert_allclose(second.theta, fit.theta, atol=1e-10)


def test_extremes_and_raw_score_sufficiency(fitted):
    _, _, _, fit = fitted
    data = np.array([[0] * 12, [1] * 12, [1] * 6 + [0] * 6, [0] * 6 + [1] * 6])
    theta, uncertainty = estimate_abilities(data, fit.steps)
    assert np.all(np.isfinite(theta))
    assert np.all(uncertainty > 0)
    assert theta[0] < theta[2] < theta[1]
    assert theta[2] == pytest.approx(theta[3], abs=1e-12)


def test_sparse_items_and_cohort_are_rejected():
    matrix, _, _ = binary_data()
    matrix[:, 0] = 0
    with pytest.raises(CalibrationError, match="no-variation"):
        calibrate(matrix)
    with pytest.raises(CalibrationError, match="Insufficient"):
        calibrate(matrix[:4])


def test_missing_responses():
    matrix, _, _ = binary_data(n=400)
    matrix[::3, 0] = np.nan
    omitted = calibrate(matrix, missing_policy="omit")
    zero = calibrate(matrix, missing_policy="zero")
    filled = calibrate(np.nan_to_num(matrix))
    np.testing.assert_allclose(zero.steps, filled.steps)
    assert omitted.steps[0][0] < zero.steps[0][0]
    matrix[0] = np.nan
    with pytest.raises(CalibrationError, match="entirely missing"):
        calibrate(matrix, missing_policy="omit")


def test_pcm_probabilities_and_recovery():
    rng = np.random.default_rng(123)
    true_steps = [np.array([b - 0.6, b + 0.6]) for b in [-1, -0.5, 0, 0.5, 1]]
    theta = rng.normal(size=1500)
    matrix = np.column_stack(
        [np.array([rng.choice(3, p=p) for p in pcm_probabilities(theta, s)]) for s in true_steps]
    )
    np.testing.assert_allclose(pcm_probabilities(theta, true_steps[0]).sum(axis=1), 1)
    np.testing.assert_allclose(pcm_probabilities(0, np.array([0, 0])), [1 / 3] * 3)
    fit = calibrate(matrix, [2] * 5)
    assert fit.stable, fit.diagnostics
    assert np.sqrt(np.mean((np.array(fit.steps) - true_steps) ** 2)) < 0.18
    a, _ = estimate_abilities(np.array([[0, 2, 1, 1, 0], [1, 1, 0, 0, 2]]), fit.steps)
    assert a[0] == pytest.approx(a[1], abs=1e-12)


def test_invalid_categories():
    with pytest.raises(CalibrationError):
        calibrate(np.full((100, 5), 0.5))


def test_standardization():
    mean, sd = reference_statistics(np.array([-1.0, 0.0, 1.0]))
    z, t = standardize(1.0, mean, sd)
    assert z == pytest.approx(np.sqrt(1.5))
    assert t == pytest.approx(50 + 10 * z)
    with pytest.raises(ValueError):
        reference_statistics(np.array([1.0]))
    with pytest.raises(ValueError):
        reference_statistics(np.ones(5))
    with pytest.raises(ValueError):
        standardize(1, 0, 0)


@pytest.mark.parametrize(
    "t,grade",
    [
        (70, "A+"),
        (69.999, "A"),
        (65, "A"),
        (60, "B+"),
        (55, "B"),
        (50, "C+"),
        (46, "C"),
        (45.999, "Below C"),
    ],
)
def test_grades(t, grade):
    assert assign_grade(t) == grade


def test_unconverged_is_flagged():
    matrix, _, _ = binary_data(n=300)
    fit = calibrate(matrix, max_iterations=1)
    assert not fit.stable
    assert "optimizer_not_converged" in fit.diagnostics["flags"]
