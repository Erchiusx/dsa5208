#!/usr/bin/env python3
"""Evaluate fixed, non-learned rainfall forecasting baselines."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pyspark.sql import DataFrame, functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import build_spark  # noqa: E402


RULE_NAMES = ("always_negative", "rain_in_current_5m", "persistence_last_30m_exceeds_r")


def rules() -> dict[str, object]:
    """Create Column expressions only after a SparkContext exists."""
    return {
        "always_negative": F.lit(False),
        "rain_in_current_5m": F.col("rainfall_last_5m_mm") > 0,
        "persistence_last_30m_exceeds_r": F.col("rainfall_last_30m_mm") > F.col("_rainfall_threshold_mm"),
    }


def report_for_year(frame: DataFrame, rainfall_threshold_mm: float) -> dict[str, object]:
    labeled = frame.filter("history_60m_complete AND future_30m_complete").withColumns(
        {
            "label": (F.col("future_30m_rainfall_mm") > F.lit(rainfall_threshold_mm)).cast("long"),
            "_rainfall_threshold_mm": F.lit(rainfall_threshold_mm),
        }
    )
    expressions = [F.count("*").alias("rows"), F.sum("label").alias("positives")]
    for name, prediction in rules().items():
        expressions.extend(
            [
                F.sum(((F.col("label") == 1) & prediction).cast("long")).alias(f"{name}_tp"),
                F.sum(((F.col("label") == 0) & prediction).cast("long")).alias(f"{name}_fp"),
                F.sum(((F.col("label") == 1) & ~prediction).cast("long")).alias(f"{name}_fn"),
            ]
        )
    raw = labeled.agg(*expressions).first().asDict()
    output: dict[str, object] = {"rows": int(raw["rows"]), "positive_prevalence": raw["positives"] / raw["rows"]}
    for name in RULE_NAMES:
        tp, fp, fn = (int(raw[f"{name}_{kind}"] or 0) for kind in ("tp", "fp", "fn"))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        output[name] = {
            "true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        }
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rainfall-threshold-mm", type=float, default=1.0)
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--report", type=Path, default=PROJECT_DIR / "reports" / "rule_baselines_1mm.json")
    args = parser.parse_args()
    if args.rainfall_threshold_mm < 0:
        parser.error("--rainfall-threshold-mm must be non-negative")

    spark = build_spark("dsa5208-rule-baselines")
    try:
        report = {"rainfall_threshold_mm": args.rainfall_threshold_mm, "rules": list(RULE_NAMES), "years": {}}
        for year in (2023, 2024):
            frame = spark.read.parquet(str(args.processed_dir / f"rainfall_features_{year}"))
            report["years"][str(year)] = report_for_year(frame, args.rainfall_threshold_mm)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
