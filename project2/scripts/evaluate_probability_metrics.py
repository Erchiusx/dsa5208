#!/usr/bin/env python3
"""Evaluate probability quality and classification quality on frozen splits."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pyspark.ml import PipelineModel
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.ml.functions import vector_to_array
from pyspark.sql import DataFrame, functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import build_spark  # noqa: E402


def score(model: PipelineModel, frame: DataFrame, rainfall_threshold_mm: float) -> DataFrame:
    labels = frame.filter("history_60m_complete AND future_30m_complete").withColumn(
        "label", (F.col("future_30m_rainfall_mm") > F.lit(rainfall_threshold_mm)).cast("double")
    )
    return model.transform(labels).select("label", vector_to_array("probability")[1].alias("probability_1"))


def evaluate(scored: DataFrame, decision_threshold: float) -> dict[str, float | int]:
    roc = BinaryClassificationEvaluator(labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderROC")
    pr = BinaryClassificationEvaluator(labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderPR")
    # Evaluators need rawPrediction; reconstruct it from the already transformed
    # probability score only for score-quality metrics below is not sufficient.
    # The caller attaches rawPrediction for those evaluator calls.
    summary = scored.select(
        F.count("*").alias("rows"), F.avg("label").alias("prevalence"),
        F.avg(F.pow(F.col("probability_1") - F.col("label"), 2)).alias("brier_score"),
        F.sum(((F.col("label") == 1) & (F.col("probability_1") >= decision_threshold)).cast("long")).alias("tp"),
        F.sum(((F.col("label") == 0) & (F.col("probability_1") >= decision_threshold)).cast("long")).alias("fp"),
        F.sum(((F.col("label") == 1) & (F.col("probability_1") < decision_threshold)).cast("long")).alias("fn"),
    ).first().asDict()
    tp, fp, fn = (int(summary[key] or 0) for key in ("tp", "fp", "fn"))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    prevalence, brier = float(summary["prevalence"]), float(summary["brier_score"])
    brier_reference = prevalence * (1 - prevalence)
    return {
        "rows": int(summary["rows"]), "positive_prevalence": prevalence,
        "brier_score": brier, "brier_score_climatology": brier_reference,
        "brier_skill_score": 1 - brier / brier_reference,
        "precision_at_frozen_threshold": precision, "recall_at_frozen_threshold": recall,
        "f1_at_frozen_threshold": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rainfall-threshold-mm", type=float, default=1.0)
    parser.add_argument("--model-dir", type=Path, default=PROJECT_DIR / "models" / "logistic_threshold_1mm")
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--decision-report", type=Path, default=PROJECT_DIR / "reports" / "decision_threshold_1mm.json")
    parser.add_argument("--report", type=Path, default=PROJECT_DIR / "reports" / "probability_metrics_1mm.json")
    parser.add_argument("--splits", nargs="+", choices=("validation", "test"), default=("validation", "test"))
    args = parser.parse_args()
    decision_threshold = json.loads(args.decision_report.read_text())["decision_threshold"]
    spark = build_spark("dsa5208-probability-metrics")
    try:
        model = PipelineModel.load(str(args.model_dir))
        report: dict[str, object] = {
            "rainfall_threshold_mm": args.rainfall_threshold_mm,
            "decision_threshold": decision_threshold,
            "decision_threshold_selected_on": "2023 validation only",
            "splits": {},
        }
        split_years = {"validation": 2023, "test": 2024}
        for role in args.splits:
            year = split_years[role]
            frame = spark.read.parquet(str(args.processed_dir / f"rainfall_features_{year}"))
            transformed = model.transform(
                frame.filter("history_60m_complete AND future_30m_complete").withColumn(
                    "label", (F.col("future_30m_rainfall_mm") > F.lit(args.rainfall_threshold_mm)).cast("double")
                )
            )
            scored = transformed.select("label", "rawPrediction", vector_to_array("probability")[1].alias("probability_1"))
            result = evaluate(scored, decision_threshold)
            result["roc_auc"] = BinaryClassificationEvaluator(labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderROC").evaluate(scored)
            result["pr_auc"] = BinaryClassificationEvaluator(labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderPR").evaluate(scored)
            report["splits"][role] = result
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
