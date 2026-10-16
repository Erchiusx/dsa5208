#!/usr/bin/env python3
"""Compare ZILN with the nonparametric amount models (and equal-weight ensembles) on 2024.

Every model is turned into the same grid forecast S[k] = P(Y > GRID[k]) on identical rows.
2023 chooses each model's F1 cutoff and the pre-declared winner (lowest 2023 log score over
the grid classes); 2024 is scored with Spark MLlib's BinaryClassificationEvaluator,
Brier / BSS, precision / recall / F1, and the proper scores of amount_models.score_columns.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.ml.functions import vector_to_array
from pyspark.sql import functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.amount_models import GRID, AmountModel, score_columns, ziln_survival  # noqa: E402
from rainfall_project.clean import build_spark  # noqa: E402
from rainfall_project.datasets import load_years  # noqa: E402
from rainfall_project.ziln import ZILNModel, best_f1_threshold, eligible, ship_package  # noqa: E402

KEY = ["station_id", "prediction_ts"]
THRESHOLDS = (0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ziln-dir", type=Path, default=PROJECT_DIR / "models" / "ziln_rich_B")
    parser.add_argument("--amount-dirs", type=Path, nargs="*", default=[])
    parser.add_argument("--ensembles", nargs="*", default=[], help="e.g. ziln+hazard (equal-weight linear pool)")
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--work-dir", type=Path, default=PROJECT_DIR / "data" / "interim" / "amount_eval")
    parser.add_argument("--report", type=Path, default=PROJECT_DIR / "reports" / "amount_models_evaluation.json")
    parser.add_argument("--sample", type=float, default=1.0, help="row fraction (smoke tests only)")
    args = parser.parse_args()
    assert all(r in GRID for r in THRESHOLDS)

    spark = build_spark("dsa5208-rainfall-amount-evaluation")
    ship_package(spark)
    spark.sparkContext.setLogLevel("ERROR")
    try:
        ziln = ZILNModel.load(args.ziln_dir)
        fs = ziln.meta.get("feature_set", "spatial")
        amount = {}
        for d in args.amount_dirs:  # named after the directory: models/amount_mlp_s5209 -> mlp_s5209
            amount[d.name.removeprefix("amount_")] = AmountModel.load(d)
        train_y = eligible(load_years(spark, args.processed_dir, list(range(2017, 2023)), "spatial")).select("y")
        clim = train_y.agg(F.count("*").alias("n"), *[F.sum((F.col("y") > r).cast("long")).alias(f"r{i}")
                                                     for i, r in enumerate(THRESHOLDS)]).first()
        clim = {r: clim[f"r{i}"] / clim["n"] for i, r in enumerate(THRESHOLDS)}

        def path(name, year):
            return str(args.work_dir / f"{name}_{year}")

        def done(name, year):  # a write cut short (no _SUCCESS) is redone, so an interrupted run resumes
            return (args.work_dir / f"{name}_{year}" / "_SUCCESS").exists()

        for year in (2023, 2024):  # materialise the rows once so every model scores the same ones
            if not done("frame", year):
                frame = eligible(load_years(spark, args.processed_dir, [year], fs))
                frame = frame.sample(fraction=args.sample, seed=5208) if args.sample < 1 else frame
                frame.write.mode("overwrite").parquet(path("frame", year))
            frame = spark.read.parquet(path("frame", year))
            if not done("base", year):
                x = ziln.occurrence.transform(ziln.prep.transform(frame))
                (x.withColumn("pi", vector_to_array("occ_probability")[1]).select(*KEY, "y", "pi", "features")
                 .write.mode("overwrite").parquet(path("base", year)))
            base = spark.read.parquet(path("base", year))
            if not done("ziln", year):
                ziln_survival(ziln, frame, KEY).write.mode("overwrite").parquet(path("ziln", year))
            for name, model in amount.items():
                if not done(name, year):
                    model.survival(base, KEY).write.mode("overwrite").parquet(path(name, year))
                print(f"{year}: {name} grid forecasts ready", flush=True)

        def load(name, year):
            if "+" not in name:
                return spark.read.parquet(path(name, year))
            parts = name.split("+")
            out = spark.read.parquet(path(parts[0], year)).withColumnRenamed("S", "S0")
            for i, p in enumerate(parts[1:], start=1):
                out = out.join(spark.read.parquet(path(p, year)).select(*KEY, F.col("S").alias(f"S{i}")), KEY)
            s = F.col("S0")
            for i in range(1, len(parts)):
                s = F.zip_with(s, F.col(f"S{i}"), lambda a, b: a + b)
            return out.select(*KEY, "y", F.transform(s, lambda v: v / len(parts)).alias("S"))

        names = ["ziln", *amount, *args.ensembles]
        report = {"ziln_dir": os.path.relpath(args.ziln_dir, PROJECT_DIR), "grid_mm": GRID, "sample": args.sample,
                  "selection": "lowest 2023 grid log score among single models", "models": {}}
        for name in names:
            cols = []
            for i, r in enumerate(THRESHOLDS):
                cols += [F.element_at("S", GRID.index(r) + 1).alias(f"p_{i}"), (F.col("y") > r).cast("double").alias(f"l_{i}")]
            sc = score_columns()
            val = load(name, 2023).select("*", *cols, *[v.alias(k) for k, v in sc.items()]).cache()
            test = load(name, 2024).select("*", *cols, *[v.alias(k) for k, v in sc.items()]).cache()
            res = {"validation_2023": val.agg(*[F.avg(k).alias(k) for k in sc]).first().asDict(),
                   "test_2024": test.agg(F.count("*").alias("rows"), *[F.avg(k).alias(k) for k in sc]).first().asDict(),
                   "thresholds": {}}
            for i, r in enumerate(THRESHOLDS):
                p, l = f"p_{i}", f"l_{i}"
                cut, _ = best_f1_threshold(val, p, l)
                ev = {m: BinaryClassificationEvaluator(rawPredictionCol=p, labelCol=l, metricName=m).evaluate(test)
                      for m in ("areaUnderROC", "areaUnderPR")}
                a = test.agg(F.avg((F.col(p) - F.col(l)) ** 2).alias("brier"), F.avg((F.lit(clim[r]) - F.col(l)) ** 2).alias("bc"),
                             F.avg(p).alias("mean_p"), F.avg(l).alias("rate"),
                             F.sum(((F.col(p) >= cut) & (F.col(l) == 1)).cast("long")).alias("tp"),
                             F.sum(((F.col(p) >= cut) & (F.col(l) == 0)).cast("long")).alias("fp"),
                             F.sum(((F.col(p) < cut) & (F.col(l) == 1)).cast("long")).alias("fn")).first()
                prec = a["tp"] / (a["tp"] + a["fp"]) if a["tp"] + a["fp"] else 0.0
                rec = a["tp"] / (a["tp"] + a["fn"]) if a["tp"] + a["fn"] else 0.0
                res["thresholds"][f"{r:g}"] = {
                    "roc_auc": ev["areaUnderROC"], "pr_auc": ev["areaUnderPR"], "brier": a["brier"],
                    "brier_skill_score": 1 - a["brier"] / a["bc"], "mean_probability": a["mean_p"], "event_rate": a["rate"],
                    "pred_over_obs": a["mean_p"] / a["rate"] if a["rate"] else None, "decision_threshold_from_2023": cut,
                    "precision": prec, "recall": rec, "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0}
            val.unpersist(); test.unpersist()
            report["models"][name] = res
            t1 = res["thresholds"]["1"]
            print(f"{name}: 2023 log {res['validation_2023']['log_score']:.4f} | 2024 log {res['test_2024']['log_score']:.4f} "
                  f"rps {res['test_2024']['rps']:.4f} crps_grid {res['test_2024']['crps_grid']:.4f} | 1mm BSS {t1['brier_skill_score']:.4f} "
                  f"PR {t1['pr_auc']:.4f} F1 {t1['f1']:.4f}", flush=True)
        singles = [n for n in names if "+" not in n]
        report["selected"] = min(singles, key=lambda n: report["models"][n]["validation_2023"]["log_score"])
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(f"selected on 2023: {report['selected']}", flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
