#!/usr/bin/env python3
"""Train the threshold-free ZILN rainfall model on 2017-2022 and choose its variance
model (constant vs GBT) on 2023 validation likelihood. The 2024 test year is not read."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import build_spark  # noqa: E402
from rainfall_project.datasets import FEATURE_SETS, load_years  # noqa: E402
from rainfall_project.ziln import eligible, fit_ziln, select_on_validation, ship_package  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--feature-set", choices=sorted(FEATURE_SETS), default="spatial")
    parser.add_argument("--model-dir", type=Path, default=PROJECT_DIR / "models" / "ziln_spatial")
    parser.add_argument("--report", type=Path, default=PROJECT_DIR / "reports" / "ziln_spatial_validation.json")
    parser.add_argument("--max-iter", type=int, default=60)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--step-size", type=float, default=0.05)
    parser.add_argument("--occ-max-iter", type=int, help="occurrence model iterations (default: --max-iter)")
    parser.add_argument("--occ-step-size", type=float, help="occurrence model step size (default: --step-size)")
    parser.add_argument("--dry-to-wet", type=float, default=3.0, help="dry:wet ratio kept for the occurrence model")
    parser.add_argument("--seed", type=int, default=5208)
    parser.add_argument("--work-dir", type=Path, default=PROJECT_DIR / "data" / "interim" / "ziln_work",
                        help="scratch Parquet for assembled training data")
    args = parser.parse_args()

    spark = build_spark("dsa5208-rainfall-ziln")
    ship_package(spark)
    t0 = time.time()
    log = lambda msg: print(f"[{time.time() - t0:7.0f}s] {msg}", flush=True)  # noqa: E731
    try:
        train = eligible(load_years(spark, args.processed_dir, list(range(2017, 2023)), args.feature_set))
        model = fit_ziln(train, dry_to_wet=args.dry_to_wet, max_iter=args.max_iter, max_depth=args.max_depth,
                         step_size=args.step_size, occ_max_iter=args.occ_max_iter,
                         occ_step_size=args.occ_step_size, features=FEATURE_SETS[args.feature_set], work_dir=args.work_dir,
                         seed=args.seed, log=log)

        validation = eligible(load_years(spark, args.processed_dir, [2023], args.feature_set))
        selection = select_on_validation(model, validation, log)
        model.meta.update({"train_years": list(range(2017, 2023)), "validation_year": 2023, "feature_set": args.feature_set,
                           "selection_2023": selection, "selection_rule": "lowest 2023 lattice NLL over sigma x error distribution"})
        model.save(args.model_dir)
        report = {"model_dir": os.path.relpath(args.model_dir, PROJECT_DIR), **model.meta,
                  "test_set_status": "not evaluated; run evaluate_ziln.py"}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        log(f"selected sigma={model.sigma_mode}, errors={model.error_dist}; saved model to {args.model_dir}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
