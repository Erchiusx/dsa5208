#!/usr/bin/env bash
# (1) a second MLP seed on the original data; (2) occurrence + MLP refitted on the QC data.
set -euo pipefail
cd ~/code/dsa5208-p2/project2
source experiments/distributional/sparkenv.sh
LOCK=/Users/miaaa/code/dsa5208-p2/.spark.lock
SPARK_COMMON='--master local[10] --conf spark.sql.shuffle.partitions=40 --conf spark.ui.showConsoleProgress=false pyspark-shell'
train() { PYSPARK_SUBMIT_ARGS="--driver-memory 9g $SPARK_COMMON" lockf "$LOCK" $PYTHON scripts/train_amount_model.py "$@"; }
evaluate() { PYSPARK_SUBMIT_ARGS="--driver-memory 7g $SPARK_COMMON" lockf "$LOCK" $PYTHON scripts/evaluate_amount_models.py "$@"; }
boot() { PYSPARK_SUBMIT_ARGS="--driver-memory 5g $SPARK_COMMON" lockf "$LOCK" $PYTHON scripts/bootstrap_amount_models.py "$@"; }

[ -d models/amount_mlp_s5209 ] || train --kind mlp --seed 5209 --model-dir models/amount_mlp_s5209
[ -d models/amount_mlp_qc ] || train --kind mlp --ziln-dir models/ziln_rich_qc --processed-dir data/processed_qc \
    --work-dir data/interim/amount_work_qc --model-dir models/amount_mlp_qc

evaluate --amount-dirs models/amount_mlp models/amount_mlp_s5209 --report reports/amount_models_seed_check.json
boot --models mlp_s5209 ziln --report reports/amount_bootstrap_mlp_s5209_vs_ziln.json
boot --models mlp_s5209 mlp --report reports/amount_bootstrap_mlp_s5209_vs_mlp.json

evaluate --ziln-dir models/ziln_rich_qc --processed-dir data/processed_qc --work-dir data/interim/amount_eval_qc \
    --amount-dirs models/amount_mlp_qc --report reports/amount_models_qc_evaluation.json
boot --models mlp_qc ziln --work-dir data/interim/amount_eval_qc --processed-dir data/processed_qc \
    --report reports/amount_bootstrap_mlp_qc_vs_ziln_qc.json
echo ALL DONE
