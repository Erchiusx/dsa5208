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

## Source and scope

Source: National Environment Agency, [Historical Rainfall across Singapore](https://data.gov.sg/collections/2279/view).
The portal warns that records can be missing and have not received the quality
control applied to official climate records. All timestamps are Singapore Time
(SGT) in ISO 8601 format. These caveats must be carried into Task 1 and model
evaluation.
