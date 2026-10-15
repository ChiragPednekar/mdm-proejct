# Failure-Risk Prediction: Method and Results

> **Status of the shipped model: DEMONSTRATION.** It is trained on the synthetic dataset produced
> by `scripts/seed.py`. The numbers below show that the pipeline works and is evaluated honestly;
> they are **not** evidence of real-world predictive performance.

## 1. Question and target

*Will this product have another qualifying failure within the next H days (H = 30 by default)?*

```
label(product, cutoff) = 1  if a service request whose fault category counts as a failure
                            is reported in [cutoff, cutoff + H)
                       = 0  otherwise, and ONLY IF the whole window [cutoff, cutoff + H)
                            lies before the data-extraction time
```

- Snapshots whose horizon is not yet fully observed are **excluded**, not labelled 0
  (right-censoring). A unit that has not failed in the last 10 days is unknown, not negative.
- Non-failure visits (installation, preventive maintenance) never count as failures.
- Units replaced before the cutoff (`outcome = 'Unit Replaced'`) are no longer observed.

## 2. Point-in-time features (no leakage)

One function, `app/ml/features.py::compute_features(history, cutoff)`, is used for both training
snapshots and live scoring. It only sees:

- service requests with `reported_at < cutoff`;
- repairs with `repair_date < cutoff`. A request reported before the cutoff but repaired after it
  contributes the request, not the repair;
- warranty contract dates, which are known when the contract is sold.

It never uses resolutions, labels, inventory, or anything recorded after the cutoff.
`tests/test_ml.py::test_no_future_leakage` adds future events to a history and asserts the
features do not change.

| Group | Features |
|---|---|
| Unit age | product age, days since installation, days since warranty start |
| Product identity | category, manufacturer, model, purchase price, model age |
| Warranty position | warranty in force, days remaining, has extended/ADP coverage |
| Lifetime service history | prior requests, prior failures, prior repairs, parts replaced, repair spend, customer-induced incidents |
| Recent history | failures in last 30/90/180 days, days since last repair, unsuccessful attempts, last fault category |

Missing values (e.g. no installation date, never repaired) are handled inside the fitted
pipeline: median imputation with missing-indicator columns for numeric features, a constant
`"None"` category for categoricals, and one-hot encoding that tolerates unseen categories.

## 3. Dataset and split

Snapshots are taken on the 1st of every month for every eligible product
(4,157 snapshots, 179 products, positive rate 4.4% for anchor date 2026-10-15).

The split is **temporal**, never random. Random splitting would put later snapshots of the same
unit in training and earlier ones in test:

| Period | Cutoffs | Snapshots | Failures |
|---|---|---|---|
| Train | 2023-07-01 → 2025-05-01 | 1,510 | 63 |
| Validation | 2025-06-01 → 2026-01-01 | 1,259 | 59 |
| Test | 2026-02-01 → 2026-09-01 | 1,388 | 60 |

A training snapshot's label looks H days ahead, so any training (validation) snapshot whose label
window would reach into the validation (test) period is dropped. With monthly cutoffs and H = 30
nothing needed dropping in this run; for longer horizons the gap removes overlapping snapshots
(`test_temporal_split_has_gap`).

## 4. Models, selection, threshold

| Model | Role |
|---|---|
| Prior-rate baseline | Predicts the training failure rate for everyone |
| Recent-failure rule | Training failure rate for units with vs. without a failure in the last 90 days |
| **Random Forest** (400 trees, min leaf 15) | Primary classifier |
| Gradient Boosting (150 depth-2 trees) | Comparison; replaces RF only if its validation PR-AUC is > 0.01 higher |

- No class re-weighting: probabilities should stay close to observed frequencies, because risk
  bands are defined on probabilities. (An early class-weighted forest was badly calibrated, with a
  Brier score of 0.072 against the baseline's 0.041, and was rejected.)
- **Decision threshold** = the probability that maximises F1 on the **validation** period
  (0.103 in this run). It is the evaluated operating point, used in the UI as "inspect".
- **Risk bands** (Low < 0.30 ≤ Medium < 0.60 ≤ High) are configurable communication labels
  (Settings page). They are deliberately separate from the validated threshold.
- After evaluation, the chosen configuration is refit on all eligible snapshots for deployment;
  the reported metrics come from the train-only fit.

## 5. Results on the held-out test period (synthetic data, anchor 2026-10-15)

| Model | Val PR-AUC | Test PR-AUC | Test ROC-AUC | Precision | Recall | F1 | Brier |
|---|---|---|---|---|---|---|---|
| Prior-rate baseline | 0.047 | 0.043 | 0.500 | 0.043 | 1.000 | 0.083 | 0.041 |
| Recent-failure rule | 0.058 | 0.080 | 0.630 | 0.043 | 1.000 | 0.083 | 0.040 |
| **Random Forest (deployed)** | 0.108 | **0.199** | **0.786** | 0.199 | 0.483 | 0.282 | **0.039** |
| Gradient Boosting | 0.112 | 0.127 | 0.727 | 0.137 | 0.367 | 0.199 | 0.040 |

Confusion matrix (RF, threshold 0.103): TN 1,211 · FP 117 · FN 31 · TP 29.

How to read this:

- With 4.3% failures, a model that always says "no failure" is 95.7% accurate, so accuracy is
  reported but not used. PR-AUC is the headline metric. The random baseline equals the
  prevalence (0.043); the forest reaches 0.199, about 4.6× better.
- At the chosen threshold the model flags about 10% of units and catches 48% of next-month
  failures, with about 1 in 5 flags being correct. That is a plausible proactive-inspection
  trade-off, not a precise predictor.
- Calibration is reasonable (Brier 0.039, below both baselines). Absolute probabilities are low
  because 30-day failures are rare, so almost every unit falls in the Low band. That is
  expected and honest, not a bug.
- Validation PR-AUC (0.108) is lower than test (0.199): with ~60 positive snapshots per period,
  metrics are noisy. Treat second-decimal differences as noise.

**What the model relies on.** Grouped permutation importance shuffles related features
together on held-out snapshots and measures the PR-AUC drop. Lifetime service history matters
most (0.062 ± 0.010), then product identity (0.016 ± 0.006). Recent history adds little *on top
of* lifetime history (0.003 ± 0.007), because the two overlap. Unit age and warranty position
show no measurable contribution. These are associations, not causes.

Per-prediction explanations use **occlusion**: each feature is replaced by its typical value
(median / most common) and the change in probability is reported. The UI states that these are
associations, not proof of cause.

## 6. Model status: validated vs demonstration vs unavailable

| State | When | Behaviour |
|---|---|---|
| `demonstration` | Training data provenance is `synthetic_demo` (set by the seed script) | Model deployed; every prediction and metric is badged "Demonstration" |
| `validated` | Operational data, ≥ 25 test failures **and** test PR-AUC beats the best baseline | Model deployed as validated |
| not deployed | Operational data that fails the evidence bar | Run recorded as Completed with a note; nothing deployed |
| `Insufficient Data` | < 300 eligible snapshots or < 30 failures, or a period with one class | Run recorded; no artifact; predictions disabled |
| `unavailable` | No active model / artifact missing / version mismatch | `POST /predictions/...` returns **503 `model_unavailable`**; the rest of the app works; no fallback probabilities |

## 7. Synthetic data assumptions (`scripts/seed.py`, seed 42)

Each unit is simulated day by day from purchase to the anchor date with daily failure probability

```
base_rate[category] × model_reliability[model]
× (1 + 1.5·exp(−age/45))                      infant mortality
× (1 + 0.6·max(0, (age − 730)/365))           wear-out after two years
× (1 + 0.25·previous_failures)                failure-prone units
× (1 + 1.6·exp(−days_since_last_repair/30))   repeat-failure effect
× 1.6 for air conditioners in April–June      seasonal load
```

Model reliability is log-normal, and four models are deliberately ~2.2× worse. Repair outcomes:
80% fixed first time, 8% partially fixed, 7% not fixed (each followed by a successful attempt),
2.5% unit replaced (units older than 200 days). Recent complaints are left in the pipeline (Open,
Assigned, In Progress).

The model can only rediscover these artificial rules. Real failure processes are messier.

## 8. Reproduce

```bash
cd backend
.venv/bin/python -m scripts.seed --reset --anchor-date 2026-10-15
.venv/bin/python -m scripts.train_model --predict-all
```

The same anchor date reproduces the numbers above exactly (random seed 42, deterministic
models). Without `--anchor-date` the history ends today, and month-boundary alignment shifts the
metrics slightly.

## 9. Before trusting this on real data

- Collect at least a year of operational history and retrain; the classification becomes
  `validated` only if the evidence bar is met.
- Re-check calibration per category, and consider isotonic calibration if probabilities drift.
- Add usage or environmental signals only if they are actually collected (none are invented here).
- Monitor drift: compare monthly prediction distributions and realised failure rates.
