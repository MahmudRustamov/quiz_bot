from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.polynomial.hermite import hermgauss
from scipy.optimize import minimize
from scipy.special import expit, logsumexp

from quizbot.domain import CalibrationError

ALGORITHM_VERSION = "mml-normal-eap-1.0"


def rasch_probability(theta, difficulty):
    return expit(np.asarray(theta) - np.asarray(difficulty))


def pcm_probabilities(theta: float | np.ndarray, steps: np.ndarray) -> np.ndarray:
    steps = np.asarray(steps, dtype=float)
    if steps.ndim != 1 or not len(steps) or not np.all(np.isfinite(steps)):
        raise ValueError("PCM needs finite step parameters")
    theta = np.asarray(theta, dtype=float)
    if not np.all(np.isfinite(theta)):
        raise ValueError("Ability must be finite")
    logits = np.concatenate(
        [np.zeros((*theta.shape, 1)), np.cumsum(theta[..., None] - steps, axis=-1)], axis=-1
    )
    return np.exp(logits - logsumexp(logits, axis=-1, keepdims=True))


def quadrature(points: int = 41) -> tuple[np.ndarray, np.ndarray]:
    nodes, weights = hermgauss(points)
    return nodes * np.sqrt(2), np.log(weights / np.sqrt(np.pi))


def _log_likelihood(matrix, steps, nodes):
    log_lik = np.zeros((len(matrix), len(nodes)))
    probabilities = []
    for j, delta in enumerate(steps):
        # Stable log probabilities even at extreme theta or step values.
        logits = np.column_stack([np.zeros(len(nodes)), np.cumsum(nodes[:, None] - delta, axis=1)])
        logp = logits - logsumexp(logits, axis=1, keepdims=True)
        probabilities.append(np.exp(logp))
        observed = np.isfinite(matrix[:, j])
        log_lik[observed] += logp[:, matrix[observed, j].astype(int)].T
    return log_lik, probabilities


def estimate_abilities(matrix: np.ndarray, steps: list[np.ndarray], points: int = 61):
    """EAP mean and posterior SD under the same fixed N(0,1) calibration prior.

    Finite for extreme patterns. Same total on the same complete item set gives
    the same posterior (Rasch raw-score sufficiency); omitted item sets differ.
    """
    matrix = _validate_matrix(matrix, [len(s) for s in steps], "omit")
    nodes, log_weights = quadrature(points)
    likelihood, _ = _log_likelihood(matrix, steps, nodes)
    log_post = likelihood + log_weights
    posterior = np.exp(log_post - logsumexp(log_post, axis=1, keepdims=True))
    mean = posterior @ nodes
    variance = posterior @ (nodes**2) - mean**2
    return mean, np.sqrt(np.maximum(variance, 0))


def _validate_matrix(matrix, max_categories, missing_policy):
    data = np.asarray(matrix, dtype=float).copy()
    if data.ndim != 2 or data.shape[1] != len(max_categories) or not len(data):
        raise CalibrationError("Response matrix shape does not match item definitions")
    if any(m not in (1, 2) for m in max_categories):
        raise CalibrationError("Only binary and 0/1/2 PCM categories are supported")
    if np.any(np.isinf(data)):
        raise CalibrationError("Infinite responses are invalid")
    if missing_policy not in ("zero", "omit"):
        raise CalibrationError("Unknown missing response policy")
    if missing_policy == "zero":
        data[np.isnan(data)] = 0
    for j, m in enumerate(max_categories):
        x = data[np.isfinite(data[:, j]), j]
        if np.any((x < 0) | (x > m) | (x != np.floor(x))):
            raise CalibrationError(f"Invalid categories in item {j}")
    if np.any(np.all(np.isnan(data), axis=1)):
        raise CalibrationError("An entirely missing response pattern has no ability evidence")
    return data


@dataclass
class CalibrationResult:
    steps: list[np.ndarray]
    standard_errors: list[np.ndarray]
    theta: np.ndarray
    posterior_sd: np.ndarray
    diagnostics: dict

    @property
    def stable(self) -> bool:
        return self.diagnostics["converged"] and not self.diagnostics["flags"]


def calibrate(
    matrix: np.ndarray,
    max_categories: list[int] | None = None,
    *,
    missing_policy: Literal["zero", "omit"] = "zero",
    min_students: int = 100,
    min_item_responses: int = 30,
    min_category_count: int = 5,
    max_iterations: int = 500,
    points: int = 41,
) -> CalibrationResult:
    """Marginal maximum likelihood using Gaussian quadrature and analytic gradient.

    Discrimination is fixed at 1. The latent distribution is fixed N(0,1),
    identifying location and scale. Steps are free (not forced into order).
    Uncertainty uses the observed marginal information, not L-BFGS's approximate
    inverse Hessian. Missing-at-random is assumed for omitted responses.
    """
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim != 2:
        raise CalibrationError("Expected a two-dimensional response matrix")
    categories = max_categories if max_categories is not None else [1] * matrix.shape[1]
    data = _validate_matrix(matrix, categories, missing_policy)
    n, items = data.shape
    if n < max(30, min_students) or items < 3:
        raise CalibrationError(
            "Insufficient cohort: require configured student minimum and at least 3 items"
        )
    counts = []
    for j, m in enumerate(categories):
        observed = data[np.isfinite(data[:, j]), j].astype(int)
        category_counts = np.bincount(observed, minlength=m + 1)
        counts.append(category_counts.tolist())
        if len(observed) < min_item_responses or np.any(category_counts < min_category_count):
            raise CalibrationError(
                f"Item {j} has too few observations or a sparse/no-variation category: {category_counts.tolist()}"
            )
    # Missing responses must not separate the instrument into disconnected blocks.
    observed_mask = np.isfinite(data).astype(int)
    adjacency = observed_mask.T @ observed_mask > 0
    visited, frontier = {0}, [0]
    while frontier:
        current = frontier.pop()
        for neighbor in np.flatnonzero(adjacency[current]):
            if int(neighbor) not in visited:
                visited.add(int(neighbor))
                frontier.append(int(neighbor))
    if len(visited) != items:
        raise CalibrationError("Disconnected item response design")
    cuts = np.cumsum([0] + categories)
    nodes, log_weights = quadrature(points)

    def unpack(parameters):
        return [parameters[cuts[j] : cuts[j + 1]] for j in range(items)]

    def objective(parameters):
        steps = unpack(parameters)
        likelihood, probabilities = _log_likelihood(data, steps, nodes)
        joint = likelihood + log_weights
        marginal = logsumexp(joint, axis=1)
        posterior = np.exp(joint - marginal[:, None])
        gradient = np.zeros_like(parameters)
        for j, m in enumerate(categories):
            observed = np.isfinite(data[:, j])
            post = posterior[observed]
            # d log P(X=k) / d delta_s = P(X>=s) - 1(k>=s)
            tails = np.cumsum(probabilities[j][:, ::-1], axis=1)[:, ::-1]
            for s in range(1, m + 1):
                gradient[cuts[j] + s - 1] = np.sum(data[observed, j] >= s) - np.sum(
                    post @ tails[:, s]
                )
        return -float(marginal.sum()), gradient

    initial = np.zeros(cuts[-1])
    result = minimize(
        objective,
        initial,
        jac=True,
        method="L-BFGS-B",
        bounds=[(-6.0, 6.0)] * len(initial),
        options={"maxiter": max_iterations, "ftol": 1e-12, "gtol": 1e-6, "maxls": 30},
    )
    flags = []
    gradient_norm = float(np.max(np.abs(result.jac)))
    converged = bool(result.success and gradient_norm < 0.01)
    if not converged:
        flags.append("optimizer_not_converged")
    if np.any(np.abs(result.x) > 5.8):
        flags.append("parameter_at_boundary")
    eps = 1e-4
    identity = np.eye(len(initial))
    hessian = np.column_stack(
        [
            (objective(result.x + eps * e)[1] - objective(result.x - eps * e)[1]) / (2 * eps)
            for e in identity
        ]
    )
    hessian = (hessian + hessian.T) / 2
    eigenvalues = np.linalg.eigvalsh(hessian)
    condition = float(np.linalg.cond(hessian))
    if eigenvalues.min() <= 1e-7 or condition > 1e8:
        flags.append("singular_information")
        se = np.full(len(initial), np.nan)
    else:
        se = np.sqrt(np.diag(np.linalg.inv(hessian)))
        if np.any(se > 1):
            flags.append("large_parameter_uncertainty")
    steps = unpack(result.x)
    theta, posterior_sd = estimate_abilities(data, steps)
    # Compare 41/61-point integration to detect quadrature sensitivity.
    theta_base, _ = estimate_abilities(data, steps, points=points)
    quadrature_difference = float(np.max(np.abs(theta - theta_base)))
    if quadrature_difference > 0.02:
        flags.append("quadrature_sensitive")
    infit, residuals = [], np.full_like(data, np.nan)
    for j, m in enumerate(categories):
        p = pcm_probabilities(theta, steps[j])
        scores = np.arange(m + 1)
        expected = p @ scores
        variance = np.maximum(p @ (scores**2) - expected**2, 1e-8)
        observed = np.isfinite(data[:, j])
        residual = data[observed, j] - expected[observed]
        fit = float(np.sum(residual**2) / np.sum(variance[observed]))
        infit.append(fit)
        residuals[observed, j] = residual / np.sqrt(variance[observed])
    if any(v < 0.5 or v > 1.5 for v in infit):
        flags.append("item_fit_requires_review")
    # Exploratory residual correlations, not a formal proof of local independence.
    max_residual_correlation = 0.0
    for i in range(items):
        for j in range(i):
            valid = np.isfinite(residuals[:, i]) & np.isfinite(residuals[:, j])
            if (
                valid.sum() >= 50
                and np.std(residuals[valid, i]) > 1e-8
                and np.std(residuals[valid, j]) > 1e-8
            ):
                corr = float(np.corrcoef(residuals[valid, i], residuals[valid, j])[0, 1])
                max_residual_correlation = max(max_residual_correlation, corr)
    if max_residual_correlation > 0.35:
        flags.append("possible_local_dependence")
    return CalibrationResult(
        steps,
        unpack(se),
        theta,
        posterior_sd,
        {
            "converged": converged,
            "flags": flags,
            "iterations": int(result.nit),
            "negative_log_likelihood": float(result.fun),
            "gradient_max": gradient_norm,
            "information_condition": condition if np.isfinite(condition) else None,
            "category_counts": counts,
            "item_infit": infit,
            "max_positive_residual_correlation": max_residual_correlation,
            "quadrature_max_theta_difference": quadrature_difference,
            "n_students": n,
            "n_items": items,
            "quadrature_points": points,
            "missing_policy": missing_policy,
            "identification": "latent distribution fixed N(0,1)",
            "ability_method": "EAP; posterior SD conditional on estimated item parameters",
            "assumptions": "unidimensionality, local independence, fixed discrimination, normal latent population; empirical fit screens do not establish validity",
        },
    )
