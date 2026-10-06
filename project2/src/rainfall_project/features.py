"""Leakage-safe feature and target construction for 30-minute rainfall forecasts."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window, functions as F


@dataclass(frozen=True)
class FeaturePaths:
    interim_dir: Path
    output_dir: Path
    report_path: Path


def cleaned_paths(interim_dir: Path, years: list[int]) -> list[str]:
    return [str(interim_dir / f"cleaned_rainfall_{year}") for year in years]


def feature_frame(cleaned: DataFrame) -> DataFrame:
    """Create past-only features and a continuous target for (t, t + 30 min]."""
    ordered = Window.partitionBy("station_id").orderBy(F.col("observation_ts").cast("long"))
    recent_5m = ordered.rangeBetween(-300, 0)
    recent_15m = ordered.rangeBetween(-900, 0)
    recent_30m = ordered.rangeBetween(-1800, 0)
    recent_60m = ordered.rangeBetween(-3600, 0)
    future_30m = ordered.rangeBetween(1, 1800)
    base = cleaned.select(
        "station_id", "station_name", "longitude", "latitude", "observation_ts", "rainfall_mm"
    )
    return (
        base.withColumn("prediction_ts", F.col("observation_ts"))
        .withColumn("rainfall_last_5m_mm", F.sum("rainfall_mm").over(recent_5m))
        .withColumn("rainfall_last_15m_mm", F.sum("rainfall_mm").over(recent_15m))
        .withColumn("rainfall_last_30m_mm", F.sum("rainfall_mm").over(recent_30m))
        .withColumn("rainfall_last_60m_mm", F.sum("rainfall_mm").over(recent_60m))
        .withColumn("history_5m_observations", F.count("rainfall_mm").over(recent_5m))
        .withColumn("history_15m_observations", F.count("rainfall_mm").over(recent_15m))
        .withColumn("history_30m_observations", F.count("rainfall_mm").over(recent_30m))
        .withColumn("history_60m_observations", F.count("rainfall_mm").over(recent_60m))
        .withColumn("future_30m_rainfall_mm", F.sum("rainfall_mm").over(future_30m))
        .withColumn("future_30m_observations", F.count("rainfall_mm").over(future_30m))
        .withColumn("history_60m_complete", F.col("history_60m_observations") == 13)
        .withColumn("future_30m_complete", F.col("future_30m_observations") == 6)
        .withColumn("hour_sgt", F.hour("prediction_ts"))
        .withColumn("day_of_week_sgt", F.dayofweek("prediction_ts"))
        .withColumn("month_sgt", F.month("prediction_ts"))
        .withColumn("day_of_year_sgt", F.dayofyear("prediction_ts"))
        .withColumn("hour_sin", F.sin(F.lit(6.283185307179586) * F.col("hour_sgt") / 24))
        .withColumn("hour_cos", F.cos(F.lit(6.283185307179586) * F.col("hour_sgt") / 24))
        .withColumn("month_sin", F.sin(F.lit(6.283185307179586) * F.col("month_sgt") / 12))
        .withColumn("month_cos", F.cos(F.lit(6.283185307179586) * F.col("month_sgt") / 12))
        .withColumn("year", F.year("prediction_ts"))
    )


def build_features(paths: FeaturePaths, years: list[int], spark: SparkSession) -> dict[str, object]:
    cleaned = spark.read.parquet(*cleaned_paths(paths.interim_dir, years))
    features = feature_frame(cleaned)
    complete = features.filter("history_60m_complete AND future_30m_complete")
    report = {
        "years_requested": years,
        "rows_input": cleaned.count(),
        "rows_featured": features.count(),
        "rows_complete_history_and_target": complete.count(),
        "rows_incomplete_history_or_target": features.filter(
            "NOT history_60m_complete OR NOT future_30m_complete"
        ).count(),
        "target_definition": "sum of the six five-minute readings in (prediction_ts, prediction_ts + 30 minutes]",
        "training_filter": "history_60m_complete AND future_30m_complete",
        "paths": asdict(paths),
    }
    features.write.mode("overwrite").partitionBy("year").parquet(str(paths.output_dir))
    paths.report_path.parent.mkdir(parents=True, exist_ok=True)
    paths.report_path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report
