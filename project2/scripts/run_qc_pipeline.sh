#!/bin/bash
# Rule-based QC -> rebuilt features, written next to (never over) the original data:
#   data/interim/cleaned_rainfall_<Y>  --qc_rainfall.py-->  data/interim_qc/cleaned_rainfall_<Y>
#   -> data/processed_qc/{rainfall_features,spatial_features,rich_features}_<Y>
# Reports: reports/qc_flags.csv (every flag), reports/qc_summary.json (rules, counts, rows per year).
# If SPARK_LOCK is set, every Spark stage runs under `lockf $SPARK_LOCK` (shared machine).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
: "${PYSPARK_SUBMIT_ARGS:=--master local[10] --driver-memory 9g --conf spark.sql.shuffle.partitions=40 pyspark-shell}"
export PYSPARK_SUBMIT_ARGS
years=${YEARS:-"2017 2018 2019 2020 2021 2022 2023 2024"}
IN=data/interim_qc
OUT=data/processed_qc
run() { if [ -n "${SPARK_LOCK:-}" ]; then lockf "$SPARK_LOCK" "$@"; else "$@"; fi; }
mkdir -p "$IN" "$OUT"

[ -n "${SKIP_QC:-}" ] || run $PY scripts/qc_rainfall.py --output-dir "$IN"
for y in $years; do
  run $PY scripts/build_features.py --years "$y" --interim-dir "$IN" \
    --output-dir "$OUT/rainfall_features_$y" --report "$OUT/feature_report_$y.json"
done
run $PY scripts/build_spatial_features.py --years $years --input-dir "$OUT" --output-dir "$OUT" --report-dir "$OUT"
run $PY scripts/build_rich_features.py --years $years --interim-dir "$IN" --output-dir "$OUT"
