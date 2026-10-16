#!/bin/bash
# End-to-end Spark pipeline: clean -> single-station features -> lagged spatial features.
# Writes the per-year directories that each later stage reads
# (data/interim/cleaned_rainfall_<Y>, data/processed/rainfall_features_<Y>, spatial_features_<Y>).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
: "${PYSPARK_SUBMIT_ARGS:=--master local[8] --driver-memory 12g --conf spark.sql.shuffle.partitions=32 pyspark-shell}"
export PYSPARK_SUBMIT_ARGS
years=${YEARS:-"2017 2018 2019 2020 2021 2022 2023 2024"}
for y in $years; do
  [ -d "data/interim/cleaned_rainfall_$y" ] || \
    $PY scripts/clean_rainfall.py --years "$y" --output-dir "data/interim/cleaned_rainfall_$y" --report "data/interim/quality_report_$y.json"
  [ -d "data/processed/rainfall_features_$y" ] || \
    $PY scripts/build_features.py --years "$y" --output-dir "data/processed/rainfall_features_$y" --report "data/processed/feature_report_$y.json"
done
$PY scripts/build_spatial_features.py --years $years
