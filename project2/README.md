# DSA5208 Project 2 — Singapore Rainfall Analysis and Prediction

This directory is deliberately independent of the Project 1 implementation while
remaining in the existing `dsa5208` remote.  It implements the assignment's two
deliverables: exploratory analysis of the 2017–2024 five-minute rainfall records
and a Spark ML model for the probability of exceeding a rainfall threshold in the
following 30 minutes.

## Layout

```text
project2/
├── data/
│   ├── raw/          # downloaded yearly CSVs — ignored by Git
│   ├── metadata/     # source metadata and checksums
│   ├── interim/      # cleaned/feature-ready data — ignored by Git
│   └── processed/    # analysis/model inputs — ignored by Git
├── docs/             # assignment notes and design decisions
├── models/           # trained model artifacts — ignored by Git
├── notebooks/        # exploratory Spark notebooks
├── reports/figures/  # report-ready figures
├── scripts/          # reproducible acquisition and validation commands
├── src/rainfall_project/
└── tests/
```

## Data acquisition

Run the following from the repository root after ensuring about 12 GB of free
space (the source declares roughly 9.9 GB for 2017–2024):

```bash
bash project2/scripts/download_rainfall_data.sh
python project2/scripts/verify_raw_data.py
```

The downloader gets a fresh, short-lived URL directly from the official
data.gov.sg API for each annual CSV, supports interrupted transfers, and writes
`data/metadata/download-manifest.json`. Raw data is intentionally not committed.

## Cleaning

Install the Spark dependency once, then write the audited cleaned dataset and
quality report without modifying `data/raw/`:

```bash
python3 -m pip install --user -r project2/requirements.txt
python project2/scripts/clean_rainfall.py
```

The full job produces partitioned Parquet under `data/interim/cleaned_rainfall/`
and `data/interim/quality_report.json`. It rejects malformed records, resolves
duplicate station/timestamp observations deterministically, and reports rather
than imputes gaps larger than five minutes. See `docs/cleaning-contract.md`.

## Feature base and 30-minute target

After all annual cleaning jobs have completed, build a threshold-independent
feature table:

```bash
python project2/scripts/build_features.py
```

It writes the continuous future-30-minute rainfall target and past-only features
under `data/processed/rainfall_features/`. A later model run receives threshold
`r` and defines `label = future_30m_rainfall_mm > r`; see
`docs/feature-contract.md`.

The target is rounded to 0.001 mm, the resolution of the readings, both where it is built and in
`ziln.eligible`. Without rounding, summing doubles leaves errors such as 5 × 0.4 = 2.0000000000000004.
The 2024 readings of 8–10 mm also carry float32 noise (8.6 is stored as 8.60001). Either error turns
a total of exactly r into "> r". Before the fix this flipped about 3,500 labels a year at the edges
1.4–50 mm, but none at 0.2, 0.4, 0.5 or 1 mm (`reports/label_rounding_flips.json`). Only three
readings, at S215 in 2018, have a fourth decimal, and rounding moves each by at most 0.0005 mm.

## Task 1: weather patterns

Spark reduces the QC'd readings (`data/interim_qc/`) to station-hours and rain events, and writes
small summary tables to `reports/eda/`. Matplotlib then draws `reports/figures/fig1–fig9` and writes the
headline numbers to `reports/eda/summary.json`:

```bash
cd project2 && source experiments/distributional/sparkenv.sh
export PYSPARK_SUBMIT_ARGS='--master local[10] --driver-memory 7g --conf spark.sql.shuffle.partitions=40 pyspark-shell'
$PYTHON scripts/eda_patterns.py      # ~15 min; --tables NAME ... recomputes selected CSVs only
$PYTHON scripts/plot_eda.py          # figures; needs matplotlib, pandas and scipy
```

Choices that matter for comparisons across years:
- **Monthly totals are rate-based:** rain per observed five-minute reading, times the slots in the month.
  - The 2018 outages leave whole slots missing, and the reading after a gap carries no extra rain.
    The outages are Feb (62 % of slots), Mar (72 %; the :25 and :55 readings are absent) and Aug (8 %).
  - Station-months under 50 % coverage are dropped.
- **Island-wide series average a fixed panel** of the 30 stations that report at least 70 % of every
  year. The network grew from 53–61 stations in 2017–2019 to 70–80 from 2020.
  - Aug 2018 has no usable panel station and is filled with its 2017–2024 mean (hatched in Fig. 5).
- **Station maps** show each station's totals relative to the island mean of the same months, so
  stations with different reporting periods are comparable.

The boundary drawn under the maps is the data.gov.sg *Master Plan 2019 Planning Area Boundary (No Sea)*
(`d_4765db0e87b9c86336792efe8a1f7a66`), saved as `data/metadata/planning_area_boundary_2019.geojson`.

## Baseline model

Train the first threshold-specific Logistic Regression baseline at 1 mm:

```bash
python project2/scripts/train_logistic_baseline.py --threshold-mm 1
```

It trains on 2017–2022, uses 2023 for validation, and reports final 2024
metrics separately. The threshold is part of the model invocation and saved
model name; see `docs/modeling-contract.md`.

After training, select the probability operating point using validation data
only, then evaluate the untouched 2024 test set:

```bash
python project2/scripts/select_decision_threshold.py --rainfall-threshold-mm 1
```

Train a nonlinear candidate with the same split and threshold, without exposing
the 2024 test set during model selection:

```bash
python project2/scripts/train_tree_candidate.py --model rf --threshold-mm 1
python project2/scripts/train_tree_candidate.py --model gbt --threshold-mm 1
```

## Multi-station candidate models

The original models are single-station baselines. Build leakage-safe spatial
features before comparing the four multi-station candidates. Each target row
uses its eight nearest stations only from the *previous* nominal five-minute
slot, so a source export at `:00` or `:59` cannot leak a later observation.

```bash
PYSPARK_SUBMIT_ARGS='--master local[4] --driver-memory 6g --conf spark.sql.shuffle.partitions=32 pyspark-shell' \
python3 project2/scripts/build_spatial_features.py --years 2017

# Once the 2017 smoke test is verified, build 2017--2024 one year at a time.
for year in {2017..2024}; do
  PYSPARK_SUBMIT_ARGS='--master local[4] --driver-memory 6g --conf spark.sql.shuffle.partitions=32 pyspark-shell' \
  python3 project2/scripts/build_spatial_features.py --years "$year"
done
```

Then train all models on `spatial_features_*`; model selection uses only 2023.

```bash
PYSPARK_SUBMIT_ARGS='--master local[4] --driver-memory 6g --conf spark.sql.shuffle.partitions=32 pyspark-shell' \
python3 project2/scripts/train_logistic_baseline.py --feature-set spatial --threshold-mm 1

PYSPARK_SUBMIT_ARGS='--master local[4] --driver-memory 6g --conf spark.sql.shuffle.partitions=32 pyspark-shell' \
python3 project2/scripts/train_tree_candidate.py --model rf --feature-set spatial --threshold-mm 1

PYSPARK_SUBMIT_ARGS='--master local[4] --driver-memory 6g --conf spark.sql.shuffle.partitions=32 pyspark-shell' \
python3 project2/scripts/train_tree_candidate.py --model gbt --feature-set spatial --threshold-mm 1

PYSPARK_SUBMIT_ARGS='--master local[4] --driver-memory 6g --conf spark.sql.shuffle.partitions=32 pyspark-shell' \
python3 project2/scripts/train_mlp_candidate.py --threshold-mm 1
```

## Threshold-free ZILN model (station, time, threshold → probability)

The task asks for one model that takes the station, prediction time **and rainfall
threshold** as inputs. `src/rainfall_project/ziln.py` models the whole 30-minute
rainfall distribution as a zero-inflated lognormal,

    P(Y = 0) = 1 − π(x),   log Y | Y > 0 ~ Normal(m(x), s(x)²),
    P(Y > r) = π(x) · Φ((m(x) − log r) / s(x))   for any r > 0,

where x are the leakage-safe `spatial_features_*` predictors at the station and time.
The likelihood separates, so each part is a maximum-likelihood fit with a Spark ML
estimator: a `GBTClassifier` for π (dry rows subsampled at rate q and weighted 1/q, so the
probabilities stay calibrated), a `GBTRegressor` on log Y over wet rows for m, and a
`GBTRegressor` on cross-fitted squared residuals for s² (or a constant s, chosen on 2023).
Every threshold is answered by the same fitted model and P(Y > r) is monotone in r.

The commands below reproduce the whole pipeline. Each stage writes the per-year
directories that the next stage reads.

```bash
bash project2/scripts/run_pipeline.sh               # clean -> features -> spatial features, 2017-2024
python3 project2/scripts/build_rich_features.py     # slot-exact own/neighbour/storm-motion features
python3 project2/scripts/train_ziln.py --feature-set rich --occ-max-iter 120 --occ-step-size 0.2 \
    --max-iter 100 --step-size 0.1 --model-dir project2/models/ziln_rich_B
python3 project2/scripts/evaluate_ziln.py --model-dir project2/models/ziln_rich_B   # 2024, r in {0.2,...,20} mm
python3 project2/scripts/predict_rain_probability.py --model-dir project2/models/ziln_rich_B --amount-dir none \
    --station S50 --time 2024-11-03T15:00 --threshold 0.5 1 5   # ZILN alone; the final model is below
```

The variance model regresses log r² on cross-fitted residuals (so s(x) > 0). The error
distribution of log Y is chosen on 2023 among Gaussian (ZILN), a global empirical
distribution, and an empirical distribution per decile of m(x). The last one won: when a
station expects only light rain, sudden convective totals give the log-residuals a heavier
right tail, and a single Gaussian or global error law underestimates P(Y > 5 mm) by about 15%.

## Rule-based quality control (QC) of the gauge readings

The portal data have not been quality controlled, and manual inspection found faulty gauges:
stuck-at-zero periods (e.g. S24B Jan–Apr 2017, S84 Dec 2019, S226 Mar 2021) and spurious
isolated extremes (S107 on 20–21 Aug 2022, S36 in 2020–21). `src/rainfall_project/qc.py`
masks such readings with fixed, explainable rules that use only the rainfall readings and
apply identically to every year. Each station is compared with the stations within 10 km;
a neighbour's daily total counts only the hours in which the station itself reported
(*hour-matched*), and the 8 nearest neighbours covering ≥ 80 % of those hours are used.

| rule | flags | masked |
|---|---|---|
| A stuck zero | a run of consecutive exact-zero station-days (days without data do not break it) with ≥ 3 days on which the neighbour median was ≥ 5 mm | the whole run |
| B isolated extreme | station-day ≥ 100 mm while the wettest neighbour got < 15 % of it | day ± 1 |
| C phantom rain | station-day ≥ 20 mm with ≥ 1 mm in ≥ 3 different hours while the wettest of ≥ 5 neighbours got ≤ 5 % of it | day ± 1 |
| D repeat | ≥ 3 B/C days at one station, consecutive flags ≤ 30 days apart | first…last flagged day ± 1 |
| E spike | one 5-min value ≥ 5 mm, own previous/next reading < 10 % of it, no neighbour reading ≥ 1 mm within ± 30 min | that slot |

Days are SGT days of the reading's accumulation period (the reading stamped 00:00 belongs to
the previous day). Flagged readings are removed from a parallel copy of the cleaned data, so
the existing eligibility filter drops prediction rows whose own 60-min history or 30-min
target touches them, and neighbour features treat the station as unavailable.

```bash
cd project2 && source experiments/distributional/sparkenv.sh   # JDK 17 + venv ($PYTHON)
export PYSPARK_SUBMIT_ARGS='--master local[10] --driver-memory 9g --conf spark.sql.shuffle.partitions=40 pyspark-shell'
bash scripts/run_qc_pipeline.sh                # SPARK_LOCK=<file> runs each stage under lockf   # qc_rainfall.py -> data/interim_qc, then features -> data/processed_qc
$PYTHON scripts/train_ziln.py --processed-dir data/processed_qc --feature-set rich --occ-max-iter 120 --occ-step-size 0.2 \
    --max-iter 100 --step-size 0.1 --work-dir data/interim/ziln_work_qc --model-dir models/ziln_rich_qc \
    --report reports/ziln_rich_qc_validation.json
$PYTHON scripts/evaluate_ziln.py --processed-dir data/processed_qc --model-dir models/ziln_rich_qc \
    --report reports/ziln_rich_qc_evaluation.json                  # QC'd 2024
$PYTHON scripts/evaluate_ziln.py --processed-dir data/processed --model-dir models/ziln_rich_qc \
    --report reports/ziln_rich_qc_evaluation_on_original.json      # original 2024, like-for-like with ziln_rich_B
```

`reports/qc_flags.csv` lists every flag (station, period, rule, own total, hour-matched
neighbour totals); `reports/qc_summary.json` holds the thresholds, counts per year and rule,
and readings per year before/after QC; `data/interim_qc/qc_station_days` is the per-station-day
QC table.

Result: 110 flags (43 stuck-zero runs, 10 isolated-extreme and 28 phantom-rain days, 3 repeat
spans, 35 spikes) remove 313,976 of 48.5 M readings (0.65 %) and 0.62 % of the eligible rows,
in every year including 2023–24. The largest fault was not on the manual list: S36 read zero
from Dec 2018 to Aug 2020, then reported phantom rain until May 2021. Retraining the final ZILN
configuration on the QC'd data (`models/ziln_rich_qc`; 2023 again selects sigma = GBT with
errors = empirical-by-m) changes 2024 scores by at most 0.0024 in Brier skill and 0.005 in
PR-AUC across 0.2–20 mm. A second seed on the original data (`models/ziln_rich_B_seed5209`)
moves them by as much. The Gaussian error law still under-predicts P(Y > 5 mm) on 2023 by
about 17 % after QC, so the heavy right tail at low expected rain is real and not an artefact
of the faulty gauges.

## Nonparametric amount models and the final model

ZILN makes one shape assumption: given rain, log Y is a location-scale family. The models in
`src/rainfall_project/amount_models.py` drop it. They keep the ZILN occurrence model π(x) and
its assembled features and replace only the wet-amount part,

    P(Y > r | x) = π(x) · S(r | x),     S(r | x) = P(Y > r | Y > 0, x),

by an estimate of S on the edges 0.2, 0.4, 0.5, 1, 1.4, 2, 3, 5, 7, 10, 15, 20, 30, 50 mm. All
are Spark MLlib estimators trained on the 2.04 M wet rows of 2017–2022:

| candidate | estimator | S(e_j \| x) |
|---|---|---|
| hazard | `GBTClassifier` on one row per edge a wet total reaches, label 1{Y > e_j}, edge index as a feature (continuation-ratio model) | product of the hazards, monotone by construction |
| rf | `RandomForestClassifier` over the 15 wet classes (60 trees, depth 12, ≥ 200 rows per leaf) | sum of class probabilities above e_j (a quantile-regression-forest estimate on the grid) |
| mlp | `MultilayerPerceptronClassifier` (64-64 hidden, softmax over the wet classes) on asinh-transformed, standardised features with the station one-hot encoded | sum of class probabilities above e_j |

Equal-weight linear pools of ZILN with the candidates were scored as well. Every model is
turned into the same grid forecast on identical rows. The pre-declared rule picks the single
model with the lowest 2023 log score over the grid classes. 2024 plays no part in the rule, but
it is not a pristine holdout: 2024 scores were computed for every candidate and for the earlier
ZILN stages, so the development process saw them. Confidence
intervals come from a 2,000-replicate bootstrap over the 366 SGT days of 2024, because rainfall
within a day is strongly dependent.

```bash
cd project2 && source experiments/distributional/sparkenv.sh
export PYSPARK_SUBMIT_ARGS='--master local[10] --driver-memory 9g --conf spark.sql.shuffle.partitions=40 pyspark-shell'
for kind in hazard rf mlp; do $PYTHON scripts/train_amount_model.py --kind $kind; done   # models/amount_<kind>
$PYTHON scripts/evaluate_amount_models.py --amount-dirs models/amount_hazard models/amount_rf models/amount_mlp \
    --ensembles ziln+hazard ziln+rf ziln+hazard+rf ziln+hazard+rf+mlp                      # reports/amount_models_evaluation.json
$PYTHON scripts/bootstrap_amount_models.py --models mlp ziln --report reports/amount_bootstrap_mlp_vs_ziln.json
```

Candidates on the original data, scored on the rounded labels (`reports/amount_models_evaluation.json`; 6.33 M rows in 2024;
log score and CRPS lower is better, CRPS is the grid approximation on [0, 50] mm):

| model | log score 2023 | log score 2024 | CRPS 2024 | BSS 1 mm | BSS 5 mm | BSS 20 mm | P̄/obs 0.2 mm | P̄/obs 20 mm |
|---|---|---|---|---|---|---|---|---|
| ZILN (`ziln_rich_B`) | .2492 | .2465 | .1027 | .443 | .298 | .104 | 1.15 | 1.33 |
| hazard | .2331 | .2306 | .1018 | .442 | .299 | .123 | 1.02 | 0.96 |
| rf | .2344 | .2320 | .1027 | .441 | .291 | .115 | 1.01 | 1.10 |
| **mlp** (selected) | **.2319** | **.2293** | .1012 | **.451** | .305 | .120 | 1.03 | 1.11 |
| ZILN + hazard + rf + mlp | .2335 | .2308 | **.1010** | .449 | **.306** | **.127** | 1.05 | 1.13 |

The MLP is selected on 2023 and is better than ZILN on 2024 at every threshold. The
day-block 95 % intervals of the Brier-skill gain all exclude 0. Two effects contribute:

- At 0.2 mm all three nonparametric models gain about 0.02 BSS. The gauges tip in 0.2 mm
  steps, so a single tip is an atom of the wet distribution. A continuous error law cannot
  represent it, and ZILN over-predicts P(Y > 0.2 mm) by 15 %.
- From 0.5 to 5 mm only the MLP gains clearly (hazard by at most 0.0015, rf falls below ZILN). Its
  ROC and PR-AUC rise as well, so it adds discrimination, not just calibration.
- At 20 mm, where ZILN over-predicts by a third, all three gain.

Refitting the MLP with another seed (`models/amount_mlp_s5209`, `reports/amount_models_seed_check.json`)
changes no Brier skill by more than 0.0017, and every seed-to-seed interval contains 0.
These candidates were fitted before the target rounding and are only rescored. The refit of the final
MLP below shows that the training labels matter less than the choice of seed.

**Final model** = occurrence GBT of `models/ziln_rich_qc` + `models/amount_mlp_qc`, both trained
on the QC'd data:

```bash
$PYTHON scripts/train_amount_model.py --kind mlp --ziln-dir models/ziln_rich_qc --processed-dir data/processed_qc \
    --work-dir data/interim/amount_work_qc --model-dir models/amount_mlp_qc
$PYTHON scripts/evaluate_amount_models.py --ziln-dir models/ziln_rich_qc --processed-dir data/processed_qc \
    --work-dir data/interim/amount_eval_qc --amount-dirs models/amount_mlp_qc --report reports/amount_models_qc_evaluation.json
$PYTHON scripts/bootstrap_amount_models.py --models mlp_qc ziln --work-dir data/interim/amount_eval_qc \
    --processed-dir data/processed_qc --report reports/amount_bootstrap_mlp_qc_vs_ziln_qc.json
$PYTHON scripts/predict_rain_probability.py --station S50 --time 2024-11-03T15:00 --threshold 0.5 1 5   # final model by default
```

QC'd 2024 (6.30 M rows), final model against ZILN trained on the same data, with day-block 95 % intervals of the gain:

| r (mm) | 0.2 | 0.5 | 1 | 2 | 5 | 10 | 20 |
|---|---|---|---|---|---|---|---|
| BSS, ZILN | .496 | .487 | .442 | .379 | .299 | .219 | .107 |
| BSS, final | .517 | .493 | .451 | .389 | .306 | .228 | .119 |
| gain | +.021 [.017, .026] | +.006 [.003, .008] | +.009 [.005, .014] | +.010 [.004, .019] | +.008 [.004, .012] | +.010 [.004, .014] | +.013 [.007, .019] |

At 1 mm the final model has ROC-AUC .940, PR-AUC .649 and F1 .616 (F1 cut-off chosen on 2023),
and its mean probability is within 1 % of the event rate.

The final MLP was refitted after the target rounding above. `models/amount_mlp_qc_unrounded` is the
same fit on the unrounded labels and is kept only as a diagnostic. Both are scored on the rounded
2024 labels (`reports/amount_bootstrap_mlp_qc_vs_unrounded.json`):
- The log-score difference is 0.00000 [−0.00009, 0.00010].
- No Brier skill differs by more than 0.001, the size of the seed-to-seed spread.
- At 1 mm no label changed, so the 0.0006 difference there is refitting noise.

The `selected` field of `reports/amount_models_qc_evaluation.json` names the unrounded fit only
because the two tie to five decimals. The final model is the fit on the correct labels. The prediction script answers the
grid edges exactly, interpolates log-log between them and extends the last segment as a
Pareto tail beyond 50 mm, so any r ≥ 0 gets a probability that is monotone in r.

## Final-model diagnostics and report

```bash
$PYTHON scripts/evaluate_amount_models.py --ziln-dir models/ziln_rich_qc --processed-dir data/processed \
    --work-dir data/interim/amount_eval_final_orig --amount-dirs models/amount_mlp_qc \
    --report reports/final_model_on_original_2024.json     # original (not QC'd) 2024 rows, like-for-like with the baselines
$PYTHON scripts/diagnose_final_model.py    # reports/final_model/{reliability,stratified}.csv
$PYTHON scripts/plot_model.py              # fig10, fig11 and reports/final_model/summary.json
tectonic -X compile docs/latex/main.tex --outdir output/pdf   # the PDF report
```

QC removes test rows whose target window holds a flagged reading, so scores on the QC'd 2024 rows depend
slightly on the outcome. `final_model_on_original_2024.json` scores the final model on all eligible original
2024 rows, the same rows as the single-threshold baselines.

## Source and scope

Source: National Environment Agency, [Historical Rainfall across Singapore](https://data.gov.sg/collections/2279/view).
The portal warns that records can be missing and have not received the quality
control applied to official climate records. All timestamps are Singapore Time
(SGT) in ISO 8601 format. These caveats must be carried into Task 1 and model
evaluation.
