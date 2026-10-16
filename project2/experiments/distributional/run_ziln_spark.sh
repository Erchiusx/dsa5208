#!/bin/bash
# Config A: the baseline GBT's hyperparameters for every part. Config B: converged occurrence model.
# Selection uses 2023 validation lattice NLL only; the selected model alone is scored on 2024.
set -euo pipefail
cd ~/code/dsa5208-p2/project2
source experiments/distributional/sparkenv.sh
export PYSPARK_SUBMIT_ARGS='--master local[8] --driver-memory 14g --conf spark.sql.shuffle.partitions=32 --conf spark.ui.showConsoleProgress=false pyspark-shell'
$PYTHON scripts/train_ziln.py --model-dir models/ziln_spatial_A --report reports/ziln_spatial_A_validation.json
$PYTHON scripts/train_ziln.py --occ-max-iter 120 --occ-step-size 0.2 --max-iter 100 --step-size 0.1 \
  --model-dir models/ziln_spatial_B --report reports/ziln_spatial_B_validation.json
best=$($PYTHON - <<'PY'
import json
v = {c: json.load(open(f"reports/ziln_spatial_{c}_validation.json")) for c in "AB"}
score = {c: min(m["nll_lattice"] for m in r["sigma_selection_2023"].values()) for c, r in v.items()}
print(min(score, key=score.get))
PY
)
echo "selected config $best on 2023 validation"
rm -rf models/ziln_spatial && cp -R "models/ziln_spatial_$best" models/ziln_spatial
$PYTHON scripts/evaluate_ziln.py --model-dir models/ziln_spatial --report reports/ziln_spatial_evaluation.json
