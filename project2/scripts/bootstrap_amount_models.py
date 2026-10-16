#!/usr/bin/env python3
"""Day-block bootstrap of score differences between two grid forecasts on 2024.

Reads the grid forecasts written by evaluate_amount_models.py (identical rows for every model),
sums each row's score difference by SGT day, and resamples days with replacement, so the
confidence intervals respect the strong within-day dependence of rainfall.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from pyspark.sql import functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.amount_models import GRID, score_columns  # noqa: E402
from rainfall_project.clean import build_spark  # noqa: E402
from rainfall_project.datasets import load_years  # noqa: E402
from rainfall_project.ziln import eligible  # noqa: E402

KEY = ["station_id", "prediction_ts"]
THRESHOLDS = (0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs=2, default=["mlp", "ziln"], help="candidate and reference")
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--work-dir", type=Path, default=PROJECT_DIR / "data" / "interim" / "amount_eval")
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--reps", type=int, default=2000)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    a, b = args.models

    spark = build_spark("dsa5208-rainfall-amount-bootstrap")
    spark.sparkContext.setLogLevel("ERROR")
    try:  # the 2017-2022 climatology that evaluate_amount_models.py uses as the BSS reference
        train_y = eligible(load_years(spark, args.processed_dir, list(range(2017, 2023)), "spatial")).select("y")
        c = train_y.agg(F.count("*").alias("n"), *[F.sum((F.col("y") > r).cast("long")).alias(f"r{i}")
                                                  for i, r in enumerate(THRESHOLDS)]).first()
        clim = [c[f"r{i}"] / c["n"] for i in range(len(THRESHOLDS))]

        def scored(name):
            df = spark.read.parquet(str(args.work_dir / f"{name}_{args.year}"))
            cols = {f"b{i}": (F.element_at("S", GRID.index(r) + 1) - (F.col("y") > r).cast("double")) ** 2
                    for i, r in enumerate(THRESHOLDS)}
            cols.update(score_columns())
            return df.select(*KEY, "y", *[v.alias(f"{name}_{k}") for k, v in cols.items()])

        score_names = list(score_columns())
        keys = [f"b{i}" for i in range(len(THRESHOLDS))] + score_names
        joined = scored(a).join(scored(b).drop("y"), KEY)
        daily = (joined.groupBy(F.to_date("prediction_ts").alias("day"))
                 .agg(F.count("*").alias("n"),
                      *[F.sum((F.col("y") > r).cast("double")).alias(f"e{i}") for i, r in enumerate(THRESHOLDS)],
                      *[F.sum(f"{a}_{k}").alias(f"A_{k}") for k in keys],
                      *[F.sum(f"{b}_{k}").alias(f"B_{k}") for k in keys])
                 .toPandas())
    finally:
        spark.stop()

    rng = np.random.default_rng(5208)
    idx = rng.integers(0, len(daily), size=(args.reps, len(daily)))
    n = daily["n"].to_numpy()

    def ci(x):
        return [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))]

    out = {"candidate": a, "reference": b, "year": args.year, "days": len(daily), "rows": int(n.sum()),
           "reps": args.reps, "scores": {}, "brier_skill_gain": {}}
    for k in score_names:  # mean score difference candidate - reference (negative favours candidate)
        d = (daily[f"A_{k}"] - daily[f"B_{k}"]).to_numpy()
        out["scores"][k] = {"diff": float(d.sum() / n.sum()), "ci95": ci(d[idx].sum(1) / n[idx].sum(1))}
    for i, r in enumerate(THRESHOLDS):
        # BSS_a - BSS_b = (Brier_b - Brier_a) / Brier_clim, with the climatological Brier of each
        # resample computed from its own events: sum (c - l)^2 = e (1 - c)^2 + (n - e) c^2
        A, B, e, cr = daily[f"A_b{i}"].to_numpy(), daily[f"B_b{i}"].to_numpy(), daily[f"e{i}"].to_numpy(), clim[i]

        def gain(A, B, e, n):
            return (B - A) / (e * (1 - cr) ** 2 + (n - e) * cr ** 2)
        point = gain(A.sum(), B.sum(), e.sum(), n.sum())
        reps = gain(A[idx].sum(1), B[idx].sum(1), e[idx].sum(1), n[idx].sum(1))
        out["brier_skill_gain"][f"{r:g}"] = {"diff": float(point), "ci95": ci(reps),
                                             "share_of_reps_positive": float((reps > 0).mean())}
    print(json.dumps(out, indent=2))
    if args.report:
        args.report.write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
