#!/bin/bash
# Rich features with config-B hyperparameters; sigma x error distribution chosen on 2023.
set -euo pipefail
cd ~/code/dsa5208-p2/project2
source experiments/distributional/sparkenv.sh
export PYSPARK_SUBMIT_ARGS='--master local[10] --driver-memory 9g --conf spark.sql.shuffle.partitions=40 --conf spark.ui.showConsoleProgress=false pyspark-shell'
$PYTHON scripts/train_ziln.py --feature-set rich --occ-max-iter 120 --occ-step-size 0.2 --max-iter 100 --step-size 0.1 \
  --model-dir models/ziln_rich_B --report reports/ziln_rich_B_validation.json
