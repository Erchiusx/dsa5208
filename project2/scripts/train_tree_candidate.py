#!/usr/bin/env python3
"""Train an RF or GBT candidate using the frozen temporal validation split."""
from __future__ import annotations

import argparse
import json
import sys
from functools import reduce
from pathlib import Path

from pyspark.ml import Pipeline
from pyspark.ml.classification import GBTClassifier, RandomForestClassifier
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.ml.feature import StringIndexer, VectorAssembler
from pyspark.sql import DataFrame, functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import build_spark  # noqa: E402


TREE_FEATURES = [
    "station_index", "longitude", "latitude", "rainfall_last_5m_mm",
    "rainfall_last_15m_mm", "rainfall_last_30m_mm", "rainfall_last_60m_mm",
    "hour_sin", "hour_cos", "month_sin", "month_cos", "day_of_week_sgt",
]


def read_years(spark, processed_dir: Path, years: list[int]) -> DataFrame:
    frames = [spark.read.parquet(str(processed_dir / f"rainfall_features_{year}")) for year in years]
    return reduce(lambda left, right: left.unionByName(right), frames)


def label(frame: DataFrame, threshold_mm: float) -> DataFrame:
    return frame.filter("history_60m_complete AND future_30m_complete").withColumn(
        "label", (F.col("future_30m_rainfall_mm") > F.lit(threshold_mm)).cast("double")
    )


def stratified_training_sample(labeled: DataFrame, negative_to_positive: float, seed: int) -> tuple[DataFrame, dict[str, object]]:
    counts = {row["label"]: int(row["count"]) for row in labeled.groupBy("label").count().collect()}
    positives, negatives = counts.get(1.0, 0), counts.get(0.0, 0)
    if positives == 0 or negatives == 0:
        raise ValueError(f"training data has a single class: {counts}")
    negative_fraction = min(1.0, negative_to_positive * positives / negatives)
    sampled = labeled.sampleBy("label", {0.0: negative_fraction, 1.0: 1.0}, seed=seed)
    sampled_counts = {row["label"]: int(row["count"]) for row in sampled.groupBy("label").count().collect()}
    total = sum(sampled_counts.values())
    weighted = sampled.withColumn(
        "class_weight",
        F.when(F.col("label") == 1.0, F.lit(total / (2 * sampled_counts[1.0]))).otherwise(
            F.lit(total / (2 * sampled_counts[0.0]))
        ),
    )
    return weighted, {
        "source_counts": {str(key): value for key, value in counts.items()},
        "sample_counts": {str(key): value for key, value in sampled_counts.items()},
        "negative_sampling_fraction": negative_fraction,
        "negative_to_positive_target": negative_to_positive,
        "seed": seed,
    }


def metrics(predictions: DataFrame) -> dict[str, float | int]:
    roc = BinaryClassificationEvaluator(labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderROC")
    pr = BinaryClassificationEvaluator(labelCol="label", rawPredictionCol="rawPrediction", metricName="areaUnderPR")
    row = predictions.select(
        F.sum(((F.col("label") == 1) & (F.col("prediction") == 1)).cast("long")).alias("tp"),
        F.sum(((F.col("label") == 0) & (F.col("prediction") == 1)).cast("long")).alias("fp"),
        F.sum(((F.col("label") == 1) & (F.col("prediction") == 0)).cast("long")).alias("fn"),
        F.count("*").alias("rows"),
    ).first().asDict()
    tp, fp, fn = (int(row[key] or 0) for key in ("tp", "fp", "fn"))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "rows": int(row["rows"]), "roc_auc": roc.evaluate(predictions), "pr_auc": pr.evaluate(predictions),
        "precision_at_0_5": precision, "recall_at_0_5": recall,
        "f1_at_0_5": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("rf", "gbt"), required=True)
    parser.add_argument("--threshold-mm", type=float, default=1.0)
    parser.add_argument("--negative-to-positive", type=float, default=3.0)
    parser.add_argument("--seed", type=int, default=5208)
    parser.add_argument("--num-trees", type=int, default=80, help="RF only")
    parser.add_argument("--max-iter", type=int, default=60, help="GBT only")
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.threshold_mm < 0 or args.negative_to_positive <= 0:
        parser.error("threshold must be non-negative and negative-to-positive must be positive")

    suffix = f"{args.model}_threshold_{args.threshold_mm:g}mm"
    model_dir = args.model_dir or PROJECT_DIR / "models" / suffix
    report_path = args.report or PROJECT_DIR / "reports" / f"{suffix}_validation.json"
    spark = build_spark(f"dsa5208-rainfall-{args.model}-candidate")
    try:
        train_source = label(read_years(spark, args.processed_dir, list(range(2017, 2023))), args.threshold_mm)
        train, sampling = stratified_training_sample(train_source, args.negative_to_positive, args.seed)
        validation = label(read_years(spark, args.processed_dir, [2023]), args.threshold_mm)
        indexer = StringIndexer(inputCol="station_id", outputCol="station_index", handleInvalid="keep")
        assembler = VectorAssembler(inputCols=TREE_FEATURES, outputCol="features", handleInvalid="error")
        common = dict(featuresCol="features", labelCol="label", weightCol="class_weight", maxDepth=args.max_depth, maxBins=128, seed=args.seed)
        classifier = (
            RandomForestClassifier(**common, numTrees=args.num_trees, featureSubsetStrategy="sqrt", subsamplingRate=0.8)
            if args.model == "rf"
            else GBTClassifier(**common, maxIter=args.max_iter, stepSize=0.05, subsamplingRate=0.8)
        )
        model = Pipeline(stages=[indexer, assembler, classifier]).fit(train)
        model.write().overwrite().save(str(model_dir))
        report = {
            "model": args.model, "threshold_mm": args.threshold_mm,
            "train_years": [2017, 2018, 2019, 2020, 2021, 2022], "validation_year": 2023,
            "features": TREE_FEATURES, "sampling": sampling,
            "validation_at_default_probability_threshold": metrics(model.transform(validation)),
            "model_dir": str(model_dir),
            "test_set_status": "not evaluated; select candidate and probability threshold using validation first",
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
