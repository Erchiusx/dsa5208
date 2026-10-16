#!/usr/bin/env python3
"""Evaluate the saved ZILN model on 2024 with Spark MLlib, for many thresholds at once.

For each threshold r the probability-cutoff for F1 is chosen on 2023 only; 2024 then
receives ROC-AUC / PR-AUC (BinaryClassificationEvaluator), Brier and Brier skill score
against the 2017-2022 climatological frequency, precision, recall and F1. Distributional
scores (CRPS, density and lattice NLL, PIT) and reliability tables are reported as well.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.sql import functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import build_spark  # noqa: E402
from rainfall_project.datasets import load_years  # noqa: E402
from rainfall_project.ziln import ship_package, ZILNModel, best_f1_threshold, eligible  # noqa: E402

THRESHOLDS = (0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0)


def climatology_crps(train_values, test_values) -> float:
    """Exact mean CRPS of the empirical 2017-2022 distribution, from (value, count) pairs."""
    import numpy as np
    v, c = (np.array(a, dtype=np.float64) for a in zip(*sorted(train_values)))
    w = c / c.sum(); cw = np.cumsum(w); cwx = np.cumsum(w * v); mean = cwx[-1]
    gini = 2 * np.sum(w * v * (2 * cw - w - 1))
    y, n = (np.array(a, dtype=np.float64) for a in zip(*test_values))
    j = np.searchsorted(v, y, side="right") - 1
    Fy = np.where(j >= 0, cw[np.maximum(j, 0)], 0.0); Sy = np.where(j >= 0, cwx[np.maximum(j, 0)], 0.0)
    eabs = y * Fy - Sy + (mean - Sy) - y * (1 - Fy)
    return float(np.sum(n * (eabs - 0.5 * gini)) / n.sum())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--model-dir", type=Path, default=PROJECT_DIR / "models" / "ziln_spatial")
    parser.add_argument("--report", type=Path, default=PROJECT_DIR / "reports" / "ziln_spatial_evaluation.json")
    parser.add_argument("--thresholds", nargs="+", type=float, default=list(THRESHOLDS))
    args = parser.parse_args()

    spark = build_spark("dsa5208-rainfall-ziln-evaluation")
    ship_package(spark)
    try:
        model = ZILNModel.load(args.model_dir)
        fs = model.meta.get("feature_set", "spatial")
        train_y = eligible(load_years(spark, args.processed_dir, list(range(2017, 2023)), fs)).select("y")
        n_train = train_y.count()
        clim = {r: train_y.filter(F.col("y") > r).count() / n_train for r in args.thresholds}
        train_values = [(row["y"], row["n"]) for row in train_y.groupBy("y").agg(F.count("*").alias("n")).collect()]

        cols = ["y", "pi", "m", "s"]
        val = model.transform(eligible(load_years(spark, args.processed_dir, [2023], fs))).select(*cols)
        test = model.transform(eligible(load_years(spark, args.processed_dir, [2024], fs))).select(*cols)
        probs = [model.exceedance(r).alias(f"p_{i}") for i, r in enumerate(args.thresholds)]
        labels = [(F.col("y") > r).cast("double").alias(f"l_{i}") for i, r in enumerate(args.thresholds)]
        val = val.select(*cols, *probs, *labels).cache()
        test = test.select(*cols, *probs, *labels, model.scores("y").alias("d")).cache()
        n_test = test.count(); val.count()

        report = {"model_dir": os.path.relpath(args.model_dir, PROJECT_DIR), "sigma_mode": model.sigma_mode,
                  "error_dist": model.error_dist, "feature_set": fs,
                  "test_year": 2024, "test_rows": n_test, "selection_year": 2023, "thresholds": {}}
        for i, r in enumerate(args.thresholds):
            p, l = f"p_{i}", f"l_{i}"
            cut, val_f1 = best_f1_threshold(val, p, l)
            ev = {m: BinaryClassificationEvaluator(rawPredictionCol=p, labelCol=l, metricName=m).evaluate(test)
                  for m in ("areaUnderROC", "areaUnderPR")}
            agg = test.agg(
                F.avg((F.col(p) - F.col(l)) ** 2).alias("brier"), F.avg((F.lit(clim[r]) - F.col(l)) ** 2).alias("brier_clim"),
                F.avg(p).alias("mean_prob"), F.avg(l).alias("event_rate"),
                F.sum(((F.col(p) >= cut) & (F.col(l) == 1)).cast("long")).alias("tp"),
                F.sum(((F.col(p) >= cut) & (F.col(l) == 0)).cast("long")).alias("fp"),
                F.sum(((F.col(p) < cut) & (F.col(l) == 1)).cast("long")).alias("fn"),
            ).first().asDict()
            brier_clim = agg["brier_clim"]
            tp, fp, fn = agg["tp"], agg["fp"], agg["fn"]
            prec = tp / (tp + fp) if tp + fp else 0.0; rec = tp / (tp + fn) if tp + fn else 0.0
            reliability = [row.asDict() for row in test.groupBy(F.least(F.floor(F.col(p) * 20), F.lit(19)).alias("bin"))
                           .agg(F.count("*").alias("n"), F.avg(p).alias("mean_prob"), F.avg(l).alias("event_rate"))
                           .orderBy("bin").collect()]
            report["thresholds"][f"{r:g}"] = {
                "roc_auc": ev["areaUnderROC"], "pr_auc": ev["areaUnderPR"], "brier": agg["brier"],
                "brier_climatology": brier_clim, "brier_skill_score": 1 - agg["brier"] / brier_clim,
                "climatology_probability_2017_2022": clim[r], "mean_probability": agg["mean_prob"],
                "event_rate": agg["event_rate"], "decision_threshold_from_2023": cut, "validation_f1": val_f1,
                "precision": prec, "recall": rec, "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
                "true_positives": tp, "false_positives": fp, "false_negatives": fn, "reliability_20_bins": reliability,
            }
            print(f"r={r:g}mm: " + json.dumps({k: round(v, 4) for k, v in report["thresholds"][f"{r:g}"].items()
                                               if isinstance(v, float)}), flush=True)

        d = test.select("d.*").withColumn("u", F.col("pit_lo") + F.rand(5208) * (F.col("pit_hi") - F.col("pit_lo")))
        dist = d.agg(F.avg("crps").alias("crps"), F.avg("nll_density").alias("nll_density"),
                     F.avg("nll_lattice").alias("nll_lattice")).first().asDict()
        pit = [row["n"] / n_test for row in d.groupBy(F.least(F.floor(F.col("u") * 10), F.lit(9)).alias("b"))
               .agg(F.count("*").alias("n")).orderBy("b").collect()]
        test_values = [(row["y"], row["n"]) for row in test.groupBy("y").agg(F.count("*").alias("n")).collect()]
        dist["crps_climatology"] = climatology_crps(train_values, test_values)
        dist["crps_skill_score"] = 1 - dist["crps"] / dist["crps_climatology"]
        dist["pit_histogram_10_bins"] = pit
        report["distribution"] = dist
        print("distribution: " + json.dumps({k: v for k, v in dist.items() if k != "pit_histogram_10_bins"}), flush=True)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
