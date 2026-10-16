#!/usr/bin/env bash
# Evaluation only (models already trained); resumes from finished grid forecasts.
set -euo pipefail
cd ~/code/dsa5208-p2/project2
source experiments/distributional/sparkenv.sh
export PYSPARK_SUBMIT_ARGS='--master local[10] --driver-memory 7g --conf spark.sql.shuffle.partitions=40 --conf spark.ui.showConsoleProgress=false pyspark-shell'
lockf /Users/miaaa/code/dsa5208-p2/.spark.lock $PYTHON scripts/evaluate_amount_models.py \
  --amount-dirs models/amount_hazard models/amount_rf models/amount_mlp \
  --ensembles ziln+hazard ziln+rf ziln+hazard+rf ziln+hazard+rf+mlp
