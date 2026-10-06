#!/usr/bin/env python3
"""Choose an F1 operating point on validation data, then evaluate the test set once."""
from __future__ import annotations

import argparse
import json
import sys
from functools import reduce
from pathlib import Path

from pyspark.ml import PipelineModel
from pyspark.ml.functions import vector_to_array
from pyspark.sql import DataFrame, functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import build_spark  # noqa: E402


def read_years(spark, processed_dir: Path, prefix: str, years: list[int]) -> DataFrame:
    frames = [spark.read.parquet(str(processed_dir / f"{prefix}_{year}")) for year in years]
    return reduce(lambda left, right: left.unionByName(right), frames)


def score(model: PipelineModel, frame: DataFrame, rainfall_threshold_mm: float) -> DataFrame:
    labeled = frame.filter("history_60m_complete AND future_30m_complete").withColumn(
        "label", (F.col("future_30m_rainfall_mm") > F.lit(rainfall_threshold_mm)).cast("long")
    )
    return model.transform(labeled).select("label", vector_to_array("probability")[1].alias("probability_1"))


def confusion(scored: DataFrame, decision_threshold: float) -> dict[str, float | int]:
    row = scored.select(
        F.sum(((F.col("label") == 1) & (F.col("probability_1") >= decision_threshold)).cast("long")).alias("tp"),
        F.sum(((F.col("label") == 0) & (F.col("probability_1") >= decision_threshold)).cast("long")).alias("fp"),
        F.sum(((F.col("label") == 1) & (F.col("probability_1") < decision_threshold)).cast("long")).alias("fn"),
        F.count("*").alias("rows"),
    ).first().asDict()
    tp, fp, fn = (int(row[key] or 0) for key in ("tp", "fp", "fn"))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "rows": int(row["rows"]), "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    }


def select_f1_threshold(scored_validation: DataFrame) -> dict[str, float | int]:
    # Binning permits an exact cumulative confusion matrix at every 0.001 score
    # threshold without materialising validation_rows × candidate_thresholds.
    binned = scored_validation.select(
        (F.floor(F.col("probability_1") * 1000) / 1000).alias("decision_threshold"), "label"
    ).groupBy("decision_threshold").agg(
        F.count("*").alias("rows_at_score"), F.sum("label").alias("positives_at_score")
    )
    # At most 1,001 bins are transferred to the driver; this avoids a global
    # Spark window while retaining the full 0.001-resolution threshold search.
    bins = binned.orderBy(F.col("decision_threshold").desc()).collect()
    total_positives = sum(int(row["positives_at_score"] or 0) for row in bins)
    cumulative_tp = cumulative_predicted_positive = 0
    best: tuple[float, float] | None = None
    for row in bins:
        cumulative_tp += int(row["positives_at_score"] or 0)
        cumulative_predicted_positive += int(row["rows_at_score"])
        f1 = 2 * cumulative_tp / (total_positives + cumulative_predicted_positive)
        candidate = (f1, float(row["decision_threshold"]))
        if best is None or candidate > best:
            best = candidate
    assert best is not None
    return {"decision_threshold": best[1], "validation_f1": best[0]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rainfall-threshold-mm", type=float, default=1.0)
    parser.add_argument("--model-dir", type=Path, default=PROJECT_DIR / "models" / "logistic_threshold_1mm")
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--feature-prefix", default="rainfall_features")
    parser.add_argument("--report", type=Path, default=PROJECT_DIR / "reports" / "decision_threshold_1mm.json")
    parser.add_argument(
        "--evaluate-test",
        action="store_true",
        help="After validation-based selection, evaluate the untouched 2024 test set.",
    )
    args = parser.parse_args()
    if args.rainfall_threshold_mm < 0:
        parser.error("--rainfall-threshold-mm must be non-negative")

    spark = build_spark("dsa5208-decision-threshold-selection")
    try:
        model = PipelineModel.load(str(args.model_dir))
        validation = score(model, read_years(spark, args.processed_dir, args.feature_prefix, [2023]), args.rainfall_threshold_mm)
        selection = select_f1_threshold(validation)
        report = {
            "rainfall_threshold_mm": args.rainfall_threshold_mm,
            "selection_dataset": "2023 validation only",
            "selection_method": "maximum F1 over probability thresholds at 0.001 resolution",
            **selection,
            "validation_at_selected_threshold": confusion(validation, selection["decision_threshold"]),
        }
        if args.evaluate_test:
            test = score(model, read_years(spark, args.processed_dir, args.feature_prefix, [2024]), args.rainfall_threshold_mm)
            report["test_at_selected_threshold"] = confusion(test, selection["decision_threshold"])
        else:
            report["test_set_status"] = "not evaluated; pass --evaluate-test only after selecting a candidate on validation"
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
