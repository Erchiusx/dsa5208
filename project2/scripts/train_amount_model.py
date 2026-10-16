#!/usr/bin/env python3
"""Fit a nonparametric wet-amount model (hazard GBT, random forest or MLP) on 2017-2022.

It reuses the feature assembly and occurrence model of a saved ZILN model, so only the
distribution of the wet amount differs between candidates; see amount_models.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from pyspark.sql import functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.amount_models import KINDS, fit_amount_model  # noqa: E402
from rainfall_project.clean import build_spark  # noqa: E402
from rainfall_project.datasets import load_years  # noqa: E402
from rainfall_project.ziln import ZILNModel, eligible, ship_package  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=KINDS, required=True)
    parser.add_argument("--ziln-dir", type=Path, default=PROJECT_DIR / "models" / "ziln_rich_B")
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--work-dir", type=Path, default=PROJECT_DIR / "data" / "interim" / "amount_work")
    parser.add_argument("--model-dir", type=Path, help="default: models/amount_<kind>")
    parser.add_argument("--params", default="{}", help="JSON overrides of the estimator parameters")
    parser.add_argument("--seed", type=int, default=5208)
    args = parser.parse_args()
    model_dir = args.model_dir or PROJECT_DIR / "models" / f"amount_{args.kind}"

    spark = build_spark(f"dsa5208-rainfall-amount-{args.kind}")
    ship_package(spark)
    t0 = time.time()
    log = lambda msg: print(f"[{time.time() - t0:7.0f}s] {msg}", flush=True)  # noqa: E731
    try:
        ziln = ZILNModel.load(args.ziln_dir)
        fs = ziln.meta.get("feature_set", "spatial")
        wet_dir = args.work_dir / "wet_train"
        if not wet_dir.exists():  # assembled once and shared by every candidate
            train = eligible(load_years(spark, args.processed_dir, list(range(2017, 2023)), fs)).filter(F.col("y") > 0)
            ziln.prep.transform(train).select("features", "y", "station_id", "prediction_ts").write.parquet(str(wet_dir))
        wet = spark.read.parquet(str(wet_dir))
        log(f"wet training rows: {wet.count():,}")
        model = fit_amount_model(args.kind, wet, args.work_dir, json.loads(args.params), args.seed, log)
        model.meta.update({"ziln_dir": os.path.relpath(args.ziln_dir, PROJECT_DIR), "feature_set": fs,
                           "train_years": list(range(2017, 2023)), "fit_seconds": round(time.time() - t0)})
        model.save(model_dir)
        log(f"saved {args.kind} model to {model_dir}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
