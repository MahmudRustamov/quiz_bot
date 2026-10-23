# Estimation and interpretation

These methods are preserved for the optional future `GRADING_STRATEGY=rasch` mode. The current default `simple` strategy calculates response-based counts/raw points only and does not run or display psychometric estimates.

## Model and identification

Binary Rasch: `P(X=1|theta,b)=logistic(theta-b)`. PCM category logits are `k*theta - sum(delta[1:k])`, with category zero logit zero. Every discrimination is fixed at one. Categories are binary 0/1 or PCM 0/1/2; mixed instruments are supported.

Item and step parameters maximize the **marginal** cohort log likelihood, integrating person likelihoods against a fixed standard normal latent distribution. Implementation: 41-point Gauss–Hermite quadrature, log-sum-exp likelihoods, analytic gradients, deterministic L-BFGS-B. Steps are bounded at ±6 for numerical protection; reaching a boundary invalidates calibration. Optimization starts at zero, then estimates parameters from responses; zero is not an assumed official difficulty.

The fixed N(0,1) population identifies location and scale. Mean item difficulty need not be zero. Independently calibrated exams are not equated. Marginal ML depends on the latent distribution: non-normal/nonrepresentative cohorts can bias estimates. This implementation does not perform conditional ML, free latent-variance estimation, anchor equating, DIF analysis, or multidimensional modeling.

Background: Johnson, [Marginal Maximum Likelihood Estimation of Item Response Models in R](https://www.jstatsoft.org/article/view/v020i10), JSS 20(10), 2007. The implementation fixes discrimination to one; this paper addresses the more general partial credit model. Alternative conditional estimation: Mair & Hatzinger, [Extended Rasch Modeling](https://www.jstatsoft.org/article/view/v020i09).

## Ability and uncertainty

Abilities are EAP posterior means under the same N(0,1) prior, using 61 quadrature points. Person uncertainty is posterior SD conditional on fitted parameters; **it omits item-calibration error**. All-zero/all-one patterns have finite, prior-dependent estimates. EAP is a shrinkage estimator, not a person maximum likelihood estimate.

On a fixed complete binary item set, the unweighted category total is sufficient for theta: equal totals yield equal EAP estimates regardless of which items were correct. This also holds for a fixed PCM item set. Harder items do not gain raw points from Rasch. Raw weights belong to grading only: a weighted total is not generally sufficient. Under default unit weights, raw and binary category totals coincide. Different omitted item sets can yield different abilities at equal observed totals.

Item/step SEs use a central finite-difference Hessian of the analytic marginal gradient, symmetrized and inverted only if positive definite/well-conditioned. L-BFGS's approximate inverse Hessian is not used as uncertainty. Failed inversions leave SEs unavailable and block publication.

## Missing responses

- Raw grading: blank/unanswered elements score zero. Manual review applies to nonblank answers only.
- `missing_policy=zero` (default): omissions enter calibration as zero.
- `missing_policy=omit`: omissions leave the likelihood, assuming ignorable/missing-at-random omissions. A PCM parent is omitted if either part is unanswered. This may be unsuitable for timed, ability-dependent omissions; choose/document the policy deliberately.
- Entirely missing person patterns, disconnected item blocks, invalid/infinite/noninteger values, and unsupported categories are rejected. Under zero, an unanswered submitted exam is an all-zero pattern; under omit it contains no ability evidence and calibration fails.
- No-variation items and sparse categories **fail calibration** rather than acquiring fabricated difficulties. Review the instrument/cohort or release raw-only results. No item/student is silently dropped.

## Optional PCM

Subparts default to separate binary items. `pcm=true` groups two subparts into a parent category 0/1/2; raw weights remain independent. PCM requires `pcm_assumptions_confirmed=true` and an `assumptions_note` documenting substantive administrator review of the ordered progression.

Two independent subparts do not automatically establish a PCM construct. Category counts and convergence cannot establish unidimensionality or local independence. Review the design, category meaning, and fit. Unordered estimated steps are permitted by the PCM parameterization and need interpretation; the optimizer does not impose ordering to manufacture progression.

## Diagnostics and publication

Require ≥3 items, the configured cohort minimum (default 100; both service and exam minimums apply), per-item observation minimum (default 30), and ≥5 observations in every category. These screening rules do not guarantee precision.

Instability flags: unsuccessful optimization or maximum gradient ≥0.01; parameter approaching ±6; singular/ill-conditioned information; any item SE >1 logit; quadrature changing theta >0.02; approximate infit outside [0.5,1.5]; positive standardized-residual correlation >0.35 with ≥50 joint observations. Diagnostics record iterations, objective, gradient, information condition, category counts, infit, residual-correlation maximum, quadrature sensitivity, assumptions, missing policy, and versions.

Infit/residual screens use EAP abilities from the same data. They are exploratory, prior-dependent checks, not formal goodness-of-fit tests. They cannot prove normality, unidimensionality, independence, invariant discrimination, ordered categories, or fairness. Stable runs are only eligible for deliberate administrator publication; expert review remains necessary. Flagged runs cannot be published as calibrated scores.

## Reference cohort and reproducibility

All reviewed submissions in the closed exam form the reference cohort. Standardization uses their EAP population mean/SD (at least two observations and positive variance). Saved policy, matrix/mapping, attempt IDs, SHA-256 snapshot hash, algorithm/library versions, parameters, posterior estimates, and mean/SD permit reconstruction. Optimization is deterministic; last-bit differences across BLAS/library versions are possible, so published numeric values are persisted too.

Regrading invalidates prior runs. Published results and their released-run pointer are immutable through services. T's cohort mean of 50 is true by construction and provides no evidence of equivalence to official Milliy Sertifikat standards.
