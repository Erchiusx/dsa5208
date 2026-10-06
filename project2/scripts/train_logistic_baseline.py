#!/usr/bin/env python3
"""Train and evaluate a time-split Spark ML rainfall baseline for one threshold."""
from __future__ import annotations

import argparse
import json
import sys
from functools import reduce
from pathlib import Path

from pyspark.ml import Pipeline
from pyspark.ml.classification import LogisticRegression
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.ml.feature import OneHotEncoder, StringIndexer, VectorAssembler
from pyspark.sql import DataFrame, functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import build_spark  # noqa: E402


NUMERIC_FEATURES = [
    "longitude", "latitude", "rainfall_last_5m_mm", "rainfall_last_15m_mm",
    "rainfall_last_30m_mm", "rainfall_last_60m_mm", "hour_sin", "hour_cos",
    "month_sin", "month_cos",
]


def read_feature_years(spark, processed_dir: Path, years: list[int]) -> DataFrame:
    frames = [spark.read.parquet(str(processed_dir / f"rainfall_features_{year}")) for year in years]
    return reduce(lambda left, right: left.unionByName(right), frames)


def with_label_and_weight(frame: DataFrame, threshold_mm: float, *, weighted: bool) -> DataFrame:
    labeled = frame.filter("history_60m_complete AND future_30m_complete").withColumn(
        "label", (F.col("future_30m_rainfall_mm") > F.lit(threshold_mm)).cast("double")
    )
    if not weighted:
        return labeled
    counts = {row["label"]: row["count"] for row in labeled.groupBy("label").count().collect()}
    if 0.0 not in counts or 1.0 not in counts:
        raise ValueError(f"threshold {threshold_mm} has a single class: {counts}")
    total = sum(counts.values())
    return labeled.withColumn(
        "class_weight",
        F.when(F.col("label") == 1.0, F.lit(total / (2 * counts[1.0]))).otherwise(
            F.lit(total / (2 * counts[0.0]))
        ),
    )


def metrics(predictions: DataFrame) -> dict[str, float | int]:
    roc = BinaryClassificationEvaluator(labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderROC")
    pr = BinaryClassificationEvaluator(labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderPR")
    confusion = predictions.select(
        F.sum(((F.col("label") == 1) & (F.col("prediction") == 1)).cast("long")).alias("tp"),
        F.sum(((F.col("label") == 0) & (F.col("prediction") == 1)).cast("long")).alias("fp"),
        F.sum(((F.col("label") == 1) & (F.col("prediction") == 0)).cast("long")).alias("fn"),
        F.count("*").alias("rows"),
    ).first().asDict()
    tp, fp, fn = (int(confusion[key] or 0) for key in ("tp", "fp", "fn"))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "rows": int(confusion["rows"]), "area_under_roc": roc.evaluate(predictions),
        "area_under_pr": pr.evaluate(predictions), "precision_at_0_5": precision,
        "recall_at_0_5": recall, "f1_at_0_5": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold-mm", type=float, default=1.0)
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.threshold_mm < 0:
        parser.error("--threshold-mm must be non-negative")
    suffix = f"{args.threshold_mm:g}mm"
    model_dir = args.model_dir or PROJECT_DIR / "models" / f"logistic_threshold_{suffix}"
    report_path = args.report or PROJECT_DIR / "reports" / f"logistic_threshold_{suffix}.json"

    spark = build_spark("dsa5208-rainfall-logistic-baseline")
    try:
        all_years = list(range(2017, 2025))
        features = read_feature_years(spark, args.processed_dir, all_years)
        train = with_label_and_weight(features.filter(F.col("year").between(2017, 2022)), args.threshold_mm, weighted=True)
        validation = with_label_and_weight(features.filter(F.col("year") == 2023), args.threshold_mm, weighted=False)
        test = with_label_and_weight(features.filter(F.col("year") == 2024), args.threshold_mm, weighted=False)

        indexer = StringIndexer(inputCol="station_id", outputCol="station_index", handleInvalid="keep")
        encoder = OneHotEncoder(inputCols=["station_index"], outputCols=["station_vector"], handleInvalid="keep")
        assembler = VectorAssembler(inputCols=["station_vector", *NUMERIC_FEATURES], outputCol="features", handleInvalid="error")
        classifier = LogisticRegression(
            featuresCol="features", labelCol="label", weightCol="class_weight", maxIter=50, regParam=0.01
        )
        model = Pipeline(stages=[indexer, encoder, assembler, classifier]).fit(train)
        model.write().overwrite().save(str(model_dir))
        report = {
            "threshold_mm": args.threshold_mm,
            "train_years": [2017, 2018, 2019, 2020, 2021, 2022],
            "validation_year": 2023, "test_year": 2024,
            "features": ["station_id", *NUMERIC_FEATURES],
            "class_weighting": "balanced by inverse class frequency on training years only",
            "validation": metrics(model.transform(validation)),
            "test": metrics(model.transform(test)),
            "model_dir": str(model_dir),
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
