#!/usr/bin/env python3
"""Where the final model is reliable and where it has skill, on the QC'd 2024 test year.

Scores the final model (occurrence GBT of the ZILN model + MLP amount model) once on the
eligible 2024 rows and writes small tables to reports/final_model/:
  * reliability.csv : rows, mean forecast and event rate per forecast-probability bin, per r;
  * stratified.csv  : Brier score of the model and of the 2017-2022 climatology per season,
                      SGT hour and recent-rain state (station wet in the last 60 min / station
                      dry but a neighbour wet / all nine gauges dry), per r.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pyspark.ml.functions import vector_to_array
from pyspark.sql import functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.amount_models import GRID, AmountModel  # noqa: E402
from rainfall_project.clean import build_spark  # noqa: E402
from rainfall_project.datasets import load_years  # noqa: E402
from rainfall_project.ziln import ZILNModel, eligible, ship_package  # noqa: E402

KEY = ["station_id", "prediction_ts"]
THRESHOLDS = (0.2, 1.0, 5.0, 20.0)
PROB_EDGES = [0.0, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001]


def season(month: F.Column) -> F.Column:
    return (F.when(month.isin(12, 1, 2, 3), "NEM").when(month.isin(4, 5), "IM1")
            .when(month.isin(6, 7, 8, 9), "SWM").otherwise("IM2"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ziln-dir", type=Path, default=PROJECT_DIR / "models" / "ziln_rich_qc")
    parser.add_argument("--amount-dir", type=Path, default=PROJECT_DIR / "models" / "amount_mlp_qc")
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed_qc")
    parser.add_argument("--work-dir", type=Path, default=PROJECT_DIR / "data" / "interim" / "final_diag")
    parser.add_argument("--out-dir", type=Path, default=PROJECT_DIR / "reports" / "final_model")
    args = parser.parse_args()

    spark = build_spark("dsa5208-final-model-diagnostics")
    ship_package(spark)
    spark.sparkContext.setLogLevel("ERROR")
    try:
        ziln, amount = ZILNModel.load(args.ziln_dir), AmountModel.load(args.amount_dir)
        fs = ziln.meta.get("feature_set", "spatial")
        train_y = eligible(load_years(spark, args.processed_dir, list(range(2017, 2023)), "spatial")).select("y")
        c = train_y.agg(F.count("*").alias("n"), *[F.sum((F.col("y") > r).cast("long")).alias(f"r{i}")
                                                  for i, r in enumerate(THRESHOLDS)]).first()
        clim = {r: c[f"r{i}"] / c["n"] for i, r in enumerate(THRESHOLDS)}

        scored_dir = args.work_dir / "scored_2024"
        if not (scored_dir / "_SUCCESS").exists():
            frame = eligible(load_years(spark, args.processed_dir, [2024], fs))
            x = ziln.occurrence.transform(ziln.prep.transform(frame))
            base = x.withColumn("pi", vector_to_array("occ_probability")[1]).select(*KEY, "y", "pi", "features")
            state = (F.when(F.col("rainfall_last_60m_mm") > 0, "station wet")
                     .when(F.col("nb_s12_max") > 0, "neighbour wet").otherwise("all dry"))
            info = frame.select(*KEY, F.col("hour_sgt").alias("hour"), season(F.col("month_sgt")).alias("season"),
                                state.alias("state"))
            (amount.survival(base, KEY).join(info, KEY)
             .select(*KEY, "y", "hour", "season", "state",
                     *[F.element_at("S", GRID.index(r) + 1).alias(f"p{i}") for i, r in enumerate(THRESHOLDS)])
             .write.mode("overwrite").parquet(str(scored_dir)))
        scored = spark.read.parquet(str(scored_dir)).cache()
        print(f"scored rows: {scored.count():,}", flush=True)

        args.out_dir.mkdir(parents=True, exist_ok=True)
        rel, strat = [], []
        for i, r in enumerate(THRESHOLDS):
            p, lab = F.col(f"p{i}"), (F.col("y") > r).cast("double")
            b = sum((p >= e).cast("int") for e in PROB_EDGES[1:-1])
            rows = (scored.groupBy(b.alias("bin")).agg(F.count("*").alias("rows"), F.avg(p).alias("mean_p"),
                                                         F.avg(lab).alias("event_rate"))
                    .toPandas().assign(r=r))
            rows["lo"] = [PROB_EDGES[k] for k in rows["bin"]]
            rows["hi"] = [min(PROB_EDGES[k + 1], 1.0) for k in rows["bin"]]
            rel.append(rows)
            agg = [F.count("*").alias("rows"), F.sum(lab).alias("events"), F.sum(p).alias("sum_p"),
                   F.sum((p - lab) ** 2).alias("brier_sum"), F.sum((F.lit(clim[r]) - lab) ** 2).alias("clim_brier_sum")]
            for g in ("season", "hour", "state"):
                strat.append(scored.groupBy(F.col(g).cast("string").alias("group")).agg(*agg).toPandas()
                             .assign(by=g, r=r))
            strat.append(scored.agg(*agg).toPandas().assign(by="all", group="all", r=r))
        import pandas as pd
        rel = pd.concat(rel).sort_values(["r", "bin"])
        rel[["r", "bin", "lo", "hi", "rows", "mean_p", "event_rate"]].to_csv(args.out_dir / "reliability.csv", index=False)
        strat = pd.concat(strat)
        strat["bss"] = 1 - strat["brier_sum"] / strat["clim_brier_sum"]
        strat[["by", "group", "r", "rows", "events", "sum_p", "brier_sum", "clim_brier_sum", "bss"]].to_csv(
            args.out_dir / "stratified.csv", index=False)
        print(strat[strat["by"].isin(["state", "all"])].to_string(index=False), flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
