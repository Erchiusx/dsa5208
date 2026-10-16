#!/usr/bin/env python3
"""P(station accumulates more than r mm in the next 30 minutes), from (station, time, r).

    python project2/scripts/predict_rain_probability.py --station S50 \
        --time 2024-11-03T15:00 --threshold 0.5 1 5

The prediction uses the station's feature row at the latest five-minute slot at or
before --time (past rainfall at the station and its lagged neighbours). The final model is

    P(Y > r) = pi(x) * S(r | x),

with pi from the ZILN occurrence GBT and S from the MLP amount model (amount_models.py),
which gives S on a grid of edges: exact at the edges, log-log interpolation between them and
a Pareto tail beyond 50 mm, so every r >= 0 is answered and P(Y > r) falls with r.
`--amount-dir none` answers from the ZILN amount distribution instead.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from pyspark.ml.functions import vector_to_array
from pyspark.sql import functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

import numpy as np  # noqa: E402

from rainfall_project.amount_models import AmountModel, survival_at  # noqa: E402
from rainfall_project.clean import build_spark  # noqa: E402
from rainfall_project.datasets import load_years  # noqa: E402
from rainfall_project.ziln import ship_package, ZILNModel  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--station", required=True, help="station_id, e.g. S50")
    parser.add_argument("--time", required=True, help="prediction time in SGT, e.g. 2024-11-03T15:00")
    parser.add_argument("--threshold", nargs="+", type=float, required=True, help="rainfall threshold(s) in mm")
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--model-dir", type=Path, default=PROJECT_DIR / "models" / "ziln_rich_qc",
                        help="ZILN model: occurrence pi(x), feature assembly and the ZILN amount fallback")
    parser.add_argument("--amount-dir", default=str(PROJECT_DIR / "models" / "amount_mlp_qc"),
                        help="amount model trained on --model-dir's features, or 'none' for the ZILN amounts")
    args = parser.parse_args()
    amount_dir = None if args.amount_dir.lower() == "none" else Path(args.amount_dir)
    when = datetime.fromisoformat(args.time)
    if any(r < 0 for r in args.threshold):
        parser.error("thresholds must be non-negative")

    spark = build_spark("dsa5208-rainfall-predict")
    ship_package(spark)
    spark.sparkContext.setLogLevel("ERROR")
    try:
        model = ZILNModel.load(args.model_dir)
        amount = AmountModel.load(amount_dir) if amount_dir else None
        if amount and (PROJECT_DIR / amount.meta["ziln_dir"]).resolve() != args.model_dir.resolve():
            parser.error(f"{amount_dir} was trained on the features of {amount.meta['ziln_dir']}, not {args.model_dir}")
        frame = load_years(spark, args.processed_dir, [when.year], model.meta.get("feature_set", "spatial"))
        ts = F.to_timestamp(F.lit(when.strftime("%Y-%m-%d %H:%M:%S")))
        row = (frame.filter((F.col("station_id") == args.station) & (F.col("prediction_ts") <= ts)
                            & (F.col("prediction_ts") > ts - F.expr("INTERVAL 5 MINUTES")))
               .orderBy(F.col("prediction_ts").desc()).limit(1))
        scored = model.transform(row)
        out = scored.select("station_id", "prediction_ts", "history_60m_complete", "pi",
                            *[model.exceedance(r).alias(f"p{i}") for i, r in enumerate(args.threshold)]
                            ).collect()
        if not out:
            raise SystemExit(f"no observation for station {args.station} within 5 minutes before {args.time}")
        o = out[0]
        probs = [o[f"p{i}"] for i in range(len(args.threshold))]
        if amount:
            key = ["station_id", "prediction_ts"]
            x = model.occurrence.transform(model.prep.transform(row))  # the inputs the amount model was trained on
            base = x.select(*key, vector_to_array("occ_probability")[1].alias("pi"), "features",
                            F.lit(None).cast("double").alias("y"))
            S = np.array(amount.survival(base, key).first()["S"])
            probs = [float(survival_at(S, r)[0]) for r in args.threshold]
        if not o["history_60m_complete"]:
            print("warning: the past 60 minutes are incomplete for this station; its rainfall sums cover only the readings present")
        source = f"{amount.kind} amount model" if amount else "ZILN amount distribution"
        print(f"station {o['station_id']} at {o['prediction_ts']} (SGT): P(any rain in next 30 min) = {o['pi']:.4f}"
              f"  [amounts: {source}]")
        for r, p in zip(args.threshold, probs):
            print(f"  P(rainfall > {r:g} mm in next 30 min) = {p:.4f}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
