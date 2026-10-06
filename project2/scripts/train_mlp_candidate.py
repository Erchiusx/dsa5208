#!/usr/bin/env python3
"""Train a Spark MLP rainfall classifier on a frozen temporal split."""
from __future__ import annotations

import argparse
import json
import sys
from functools import reduce
from pathlib import Path

from pyspark.ml import Pipeline, PipelineModel
from pyspark.ml.classification import MultilayerPerceptronClassifier
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.ml.feature import OneHotEncoder, StandardScaler, StringIndexer, VectorAssembler
from pyspark.sql import DataFrame, functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import build_spark  # noqa: E402
from rainfall_project.spatial import SPATIAL_NUMERIC_FEATURES  # noqa: E402


NUMERIC_FEATURES = [
    "longitude", "latitude", "rainfall_last_5m_mm", "rainfall_last_15m_mm",
    "rainfall_last_30m_mm", "rainfall_last_60m_mm", "hour_sin", "hour_cos",
    "month_sin", "month_cos", "day_of_week_sgt", *SPATIAL_NUMERIC_FEATURES,
]


def read_years(spark, processed_dir: Path, prefix: str, years: list[int]) -> DataFrame:
    frames = [spark.read.parquet(str(processed_dir / f"{prefix}_{year}")) for year in years]
    return reduce(lambda left, right: left.unionByName(right), frames)


def label(frame: DataFrame, rainfall_threshold_mm: float) -> DataFrame:
    return frame.filter("history_60m_complete AND future_30m_complete").withColumn(
        "label", (F.col("future_30m_rainfall_mm") > F.lit(rainfall_threshold_mm)).cast("double")
    )


def sampled_training_data(labeled: DataFrame, negative_to_positive: float, seed: int) -> tuple[DataFrame, dict[str, object]]:
    counts = {row["label"]: int(row["count"]) for row in labeled.groupBy("label").count().collect()}
    positives, negatives = counts.get(1.0, 0), counts.get(0.0, 0)
    if positives == 0 or negatives == 0:
        raise ValueError(f"training data has a single class: {counts}")
    negative_fraction = min(1.0, negative_to_positive * positives / negatives)
    sampled = labeled.sampleBy("label", {0.0: negative_fraction, 1.0: 1.0}, seed=seed)
    sampled_counts = {row["label"]: int(row["count"]) for row in sampled.groupBy("label").count().collect()}
    return sampled, {
        "source_counts": {str(key): value for key, value in counts.items()},
        "sample_counts": {str(key): value for key, value in sampled_counts.items()},
        "negative_sampling_fraction": negative_fraction,
        "negative_to_positive_target": negative_to_positive,
        "seed": seed,
        "class_weighting": "not supported by Spark MLP; class balance is controlled by seeded negative sampling",
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
    parser.add_argument("--threshold-mm", type=float, default=1.0)
    parser.add_argument("--negative-to-positive", type=float, default=3.0)
    parser.add_argument("--hidden-layers", nargs="+", type=int, default=[128, 64])
    parser.add_argument("--max-iter", type=int, default=120)
    parser.add_argument("--block-size", type=int, default=256)
    parser.add_argument("--solver", choices=("gd", "l-bfgs"), default="l-bfgs")
    parser.add_argument("--step-size", type=float, default=0.03, help="Gradient-descent learning rate; ignored by l-bfgs")
    parser.add_argument("--variant", default="centered_lbfgs", help="Artifact label; keeps runs with different settings separate")
    parser.add_argument("--seed", type=int, default=5208)
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--feature-prefix", default="spatial_features")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.threshold_mm < 0 or args.negative_to_positive <= 0 or args.step_size <= 0 or any(width < 1 for width in args.hidden_layers):
        parser.error("threshold must be non-negative; sampling ratio and hidden-layer widths must be positive")

    suffix = f"mlp_spatial_{args.variant}_threshold_{args.threshold_mm:g}mm"
    model_dir = args.model_dir or PROJECT_DIR / "models" / suffix
    report_path = args.report or PROJECT_DIR / "reports" / f"{suffix}_validation.json"
    spark = build_spark("dsa5208-rainfall-spatial-mlp")
    try:
        train_source = label(read_years(spark, args.processed_dir, args.feature_prefix, list(range(2017, 2023))), args.threshold_mm)
        train, sampling = sampled_training_data(train_source, args.negative_to_positive, args.seed)
        validation = label(read_years(spark, args.processed_dir, args.feature_prefix, [2023]), args.threshold_mm)
        preprocessor = Pipeline(stages=[
            StringIndexer(inputCol="station_id", outputCol="station_index", handleInvalid="keep"),
            OneHotEncoder(inputCols=["station_index"], outputCols=["station_vector"], handleInvalid="keep", dropLast=False),
            VectorAssembler(inputCols=NUMERIC_FEATURES, outputCol="numeric_features", handleInvalid="error"),
            # Center dense numeric predictors without densifying the station one-hot vector.
            StandardScaler(inputCol="numeric_features", outputCol="numeric_features_scaled", withStd=True, withMean=True),
            VectorAssembler(inputCols=["station_vector", "numeric_features_scaled"], outputCol="features", handleInvalid="error"),
        ]).fit(train)
        prepared_train = preprocessor.transform(train)
        input_dimension = int(prepared_train.schema["features"].metadata["ml_attr"]["num_attrs"])
        layers = [input_dimension, *args.hidden_layers, 2]
        classifier_args = dict(
            featuresCol="features", labelCol="label", layers=layers, maxIter=args.max_iter,
            blockSize=args.block_size, seed=args.seed, solver=args.solver,
        )
        if args.solver == "gd":
            classifier_args["stepSize"] = args.step_size
        classifier = MultilayerPerceptronClassifier(**classifier_args)
        classifier_model = classifier.fit(prepared_train)
        model = PipelineModel([*preprocessor.stages, classifier_model])
        model.write().overwrite().save(str(model_dir))
        report = {
            "model": "mlp", "variant": args.variant, "threshold_mm": args.threshold_mm, "feature_prefix": args.feature_prefix,
            "train_years": [2017, 2018, 2019, 2020, 2021, 2022], "validation_year": 2023,
            "features": ["station_id", *NUMERIC_FEATURES], "layers": layers, "solver": args.solver,
            "step_size": args.step_size if args.solver == "gd" else None, "numeric_standardization": "zero mean and unit variance",
            "sampling": sampling,
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
