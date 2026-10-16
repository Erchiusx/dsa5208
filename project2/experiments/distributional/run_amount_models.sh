#!/bin/bash
# Nonparametric wet-amount candidates sharing ZILN's occurrence model; each full-scale step
# takes the shared Spark lock so it never overlaps another agent's Spark job.
set -euo pipefail
cd ~/code/dsa5208-p2/project2
source experiments/distributional/sparkenv.sh
export PYSPARK_SUBMIT_ARGS='--master local[10] --driver-memory 9g --conf spark.sql.shuffle.partitions=40 --conf spark.ui.showConsoleProgress=false pyspark-shell'
LOCK=/Users/miaaa/code/dsa5208-p2/.spark.lock
for kind in hazard rf mlp; do
  [ -d "models/amount_$kind" ] || lockf "$LOCK" $PYTHON scripts/train_amount_model.py --kind "$kind"
done
lockf "$LOCK" $PYTHON scripts/evaluate_amount_models.py \
  --amount-dirs models/amount_hazard models/amount_rf models/amount_mlp \
  --ensembles ziln+hazard ziln+rf ziln+hazard+rf ziln+hazard+rf+mlp
