#!/usr/bin/env bash
# Rerun after rounding the target to 0.001 mm in ziln.eligible (float-sum and float32 noise made an exact r
# count as "> r"). The occurrence models are unaffected (their label is y > 0, which rounding never changes);
# the MLP's wet classes are, so the final MLP is refitted and every forecast is rescored on the fixed labels.
# The pre-fix MLP is kept as amount_mlp_qc_unrounded to measure the effect of the training labels alone.
set -euo pipefail
cd ~/code/dsa5208-p2/project2
source experiments/distributional/sparkenv.sh
LOCK=/Users/miaaa/code/dsa5208-p2/.spark.lock
SPARK_COMMON='--master local[10] --conf spark.sql.shuffle.partitions=40 --conf spark.ui.showConsoleProgress=false pyspark-shell'
train() { PYSPARK_SUBMIT_ARGS="--driver-memory 9g $SPARK_COMMON" lockf "$LOCK" $PYTHON scripts/train_amount_model.py "$@"; }
evaluate() { PYSPARK_SUBMIT_ARGS="--driver-memory 7g $SPARK_COMMON" lockf "$LOCK" $PYTHON scripts/evaluate_amount_models.py "$@"; }
boot() { PYSPARK_SUBMIT_ARGS="--driver-memory 5g $SPARK_COMMON" lockf "$LOCK" $PYTHON scripts/bootstrap_amount_models.py "$@"; }

if [ ! -d reports/pre_rounding ]; then
  mkdir -p reports/pre_rounding
  cp reports/amount_models_*.json reports/amount_bootstrap_*.json reports/pre_rounding/
fi
[ -d models/amount_mlp_qc_unrounded ] || mv models/amount_mlp_qc models/amount_mlp_qc_unrounded

# final model: occurrence from ziln_rich_qc + MLP refitted on the rounded labels
QC=(--ziln-dir models/ziln_rich_qc --processed-dir data/processed_qc)
[ -d models/amount_mlp_qc ] || train --kind mlp "${QC[@]}" --work-dir data/interim/amount_work_qc --model-dir models/amount_mlp_qc
evaluate "${QC[@]}" --work-dir data/interim/amount_eval_qc --amount-dirs models/amount_mlp_qc models/amount_mlp_qc_unrounded \
    --report reports/amount_models_qc_evaluation.json
boot --models mlp_qc ziln --work-dir data/interim/amount_eval_qc --processed-dir data/processed_qc \
    --report reports/amount_bootstrap_mlp_qc_vs_ziln_qc.json
boot --models mlp_qc mlp_qc_unrounded --work-dir data/interim/amount_eval_qc --processed-dir data/processed_qc \
    --report reports/amount_bootstrap_mlp_qc_vs_unrounded.json
echo FINAL MODEL DONE

# model selection on the original data, rescored on the rounded labels (candidates as trained)
evaluate --amount-dirs models/amount_hazard models/amount_rf models/amount_mlp \
    --ensembles ziln+hazard ziln+rf ziln+hazard+rf ziln+hazard+rf+mlp --report reports/amount_models_evaluation.json
evaluate --amount-dirs models/amount_mlp models/amount_mlp_s5209 --report reports/amount_models_seed_check.json
boot --models mlp ziln --report reports/amount_bootstrap_mlp_vs_ziln.json
boot --models mlp_s5209 ziln --report reports/amount_bootstrap_mlp_s5209_vs_ziln.json
boot --models mlp_s5209 mlp --report reports/amount_bootstrap_mlp_s5209_vs_mlp.json

rm -rf data/interim/amount_work_qc data/interim/amount_eval_qc data/interim/amount_eval
echo ALL DONE
