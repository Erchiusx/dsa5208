#!/usr/bin/env python3
"""Fit Platt probability calibration on a validation year for a saved classifier."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from pyspark.ml import Pipeline, PipelineModel
from pyspark.ml.classification import LogisticRegression
from pyspark.ml.functions import vector_to_array
from pyspark.ml.feature import VectorAssembler
from pyspark.sql import DataFrame, functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import build_spark  # noqa: E402


EPSILON = 1e-6


def labeled_scores(model: PipelineModel, frame: DataFrame, rainfall_threshold_mm: float) -> DataFrame:
    labeled = frame.filter("history_60m_complete AND future_30m_complete").withColumn(
        "label", (F.col("future_30m_rainfall_mm") > F.lit(rainfall_threshold_mm)).cast("double")
    )
    return model.transform(labeled).select("label", vector_to_array("probability")[1].alias("raw_probability"))


def with_logit(frame: DataFrame) -> DataFrame:
    clipped = F.least(F.greatest(F.col("raw_probability"), F.lit(EPSILON)), F.lit(1 - EPSILON))
    return frame.withColumn("raw_logit", F.log(clipped / (F.lit(1.0) - clipped)))


def probability_metrics(frame: DataFrame, probability_column: str) -> dict[str, float | int]:
    row = frame.select(
        F.count("*").alias("rows"), F.avg("label").alias("prevalence"),
        F.avg(F.pow(F.col(probability_column) - F.col("label"), 2)).alias("brier_score"),
    ).first().asDict()
    prevalence = float(row["prevalence"])
    climatology_brier = prevalence * (1.0 - prevalence)
    brier = float(row["brier_score"])
    return {
        "rows": int(row["rows"]), "positive_prevalence": prevalence,
        "brier_score": brier, "brier_score_climatology": climatology_brier,
        "brier_skill_score": 1.0 - brier / climatology_brier,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rainfall-threshold-mm", type=float, default=1.0)
    parser.add_argument("--model-dir", type=Path, default=PROJECT_DIR / "models" / "gbt_spatial_threshold_1mm")
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--feature-prefix", default="spatial_features")
    parser.add_argument("--calibration-year", type=int, default=2023)
    parser.add_argument("--evaluate-year", type=int, help="Optional held-out year; omit to evaluate calibration data only")
    parser.add_argument("--raw-decision-threshold", type=float, default=0.931)
    parser.add_argument("--calibrator-dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not 0 < args.raw_decision_threshold < 1:
        parser.error("--raw-decision-threshold must be between zero and one")

    suffix = f"platt_calibrator_{args.calibration_year}"
    calibrator_dir = args.calibrator_dir or args.model_dir.parent / f"{args.model_dir.name}_{suffix}"
    report_path = args.report or PROJECT_DIR / "reports" / f"{args.model_dir.name}_{suffix}.json"
    spark = build_spark("dsa5208-platt-calibration")
    try:
        model = PipelineModel.load(str(args.model_dir))
        calibration_frame = spark.read.parquet(str(args.processed_dir / f"{args.feature_prefix}_{args.calibration_year}"))
        calibration_scores = with_logit(labeled_scores(model, calibration_frame, args.rainfall_threshold_mm))
        calibrator = Pipeline(stages=[
            VectorAssembler(inputCols=["raw_logit"], outputCol="features"),
            LogisticRegression(featuresCol="features", labelCol="label", maxIter=50, regParam=0.0),
        ]).fit(calibration_scores)
        calibrator.write().overwrite().save(str(calibrator_dir))

        def calibrated(frame: DataFrame) -> DataFrame:
            return calibrator.transform(with_logit(frame)).select(
                "label", "raw_probability", vector_to_array("probability")[1].alias("calibrated_probability")
            )

        calibration_result = calibrated(calibration_scores)
        threshold_logit = math.log(args.raw_decision_threshold / (1.0 - args.raw_decision_threshold))
        threshold_frame = spark.createDataFrame([(threshold_logit,)], ["raw_logit"])
        calibrated_threshold = float(calibrator.transform(threshold_frame).select("probability").first()[0][1])
        report: dict[str, object] = {
            "method": "Platt scaling on logit of the base model probability",
            "base_model_dir": str(args.model_dir), "calibrator_dir": str(calibrator_dir),
            "calibration_year": args.calibration_year,
            "raw_decision_threshold": args.raw_decision_threshold,
            "equivalent_calibrated_decision_threshold": calibrated_threshold,
            "calibration_year_metrics": {
                "raw": probability_metrics(calibration_result, "raw_probability"),
                "calibrated": probability_metrics(calibration_result, "calibrated_probability"),
                "warning": "in-sample calibration metrics; use an independent year for generalization",
            },
        }
        if args.evaluate_year is not None:
            evaluation_frame = spark.read.parquet(str(args.processed_dir / f"{args.feature_prefix}_{args.evaluate_year}"))
            evaluation_result = calibrated(labeled_scores(model, evaluation_frame, args.rainfall_threshold_mm))
            report["evaluation_year"] = args.evaluate_year
            report["evaluation_metrics"] = {
                "raw": probability_metrics(evaluation_result, "raw_probability"),
                "calibrated": probability_metrics(evaluation_result, "calibrated_probability"),
                "warning": "post-hoc evaluation when the requested year was previously inspected",
            }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
