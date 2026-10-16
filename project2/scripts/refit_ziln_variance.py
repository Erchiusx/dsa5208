#!/usr/bin/env python3
"""Refit only the variance model and residual tables of a saved ZILN model from the
cross-fitted residuals written by train_ziln.py (--work-dir), then redo the 2023 choice
of sigma mode and error distribution. The occurrence and log-amount models are kept."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import build_spark  # noqa: E402
from rainfall_project.datasets import load_years  # noqa: E402
from rainfall_project.ziln import ZILNModel, eligible, fit_variance_and_errors, select_on_validation, ship_package  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, default=PROJECT_DIR / "data" / "interim" / "ziln_work")
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    spark = build_spark("dsa5208-ziln-refit-variance")
    ship_package(spark)
    t0 = time.time()
    log = lambda msg: print(f"[{time.time() - t0:7.0f}s] {msg}", flush=True)  # noqa: E731
    try:
        model = ZILNModel.load(args.model_dir)
        oof = spark.read.parquet(str(args.work_dir / "oof"))
        scale, variance_meta, quantiles = fit_variance_and_errors(oof, model.meta["gbt_params_amount"], model.sigma_const)
        model.scale, model.quantiles = scale, quantiles
        model.meta.update(variance_meta)
        log(f"refitted log-variance model (c={variance_meta['variance_scale_c']:.4f})")
        validation = eligible(load_years(spark, args.processed_dir, [2023], model.meta.get("feature_set", "spatial")))
        selection = select_on_validation(model, validation, log)
        model.meta.update({"selection_2023": selection})
        model.save(args.model_dir)
        args.report.write_text(json.dumps({k: v for k, v in model.meta.items() if k != "quantiles"}, indent=2) + "\n")
        log(f"selected sigma={model.sigma_mode}, errors={model.error_dist}; saved {args.model_dir}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
