"""Auditable cleaning for the historical five-minute rainfall CSV exports."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from pyspark.sql import DataFrame, SparkSession, Window, functions as F, types as T


RAW_SCHEMA = T.StructType(
    [
        T.StructField("date", T.StringType(), True),
        T.StructField("timestamp", T.StringType(), True),
        T.StructField("update_timestamp", T.StringType(), True),
        T.StructField("station_id", T.StringType(), True),
        T.StructField("station_name", T.StringType(), True),
        T.StructField("station_device_id", T.StringType(), True),
        T.StructField("location_longitude", T.StringType(), True),
        T.StructField("location_latitude", T.StringType(), True),
        T.StructField("reading_update_timestamp", T.StringType(), True),
        T.StructField("reading_value", T.StringType(), True),
        T.StructField("reading_type", T.StringType(), True),
        T.StructField("reading_unit", T.StringType(), True),
    ]
)


@dataclass(frozen=True)
class CleanPaths:
    raw_dir: Path
    output_dir: Path
    report_path: Path


def build_spark(app_name: str = "dsa5208-rainfall-clean") -> SparkSession:
    return (
        SparkSession.builder.appName(app_name)
        .config("spark.sql.session.timeZone", "Asia/Singapore")
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.shuffle.partitions", "32")
        .getOrCreate()
    )


def raw_paths(raw_dir: Path, years: Iterable[int]) -> list[str]:
    return [str(raw_dir / f"rainfall_{year}.csv") for year in years]


def parse_raw(spark: SparkSession, paths: list[str]) -> DataFrame:
    raw = (
        spark.read.option("header", True)
        .option("mode", "PERMISSIVE")
        .schema(RAW_SCHEMA)
        .csv(paths)
    )
    return raw.select(
        F.col("date").alias("source_date"),
        F.to_timestamp("timestamp", "yyyy-MM-dd'T'HH:mm:ssXXX").alias("observation_ts"),
        F.to_timestamp("update_timestamp", "yyyy-MM-dd'T'HH:mm:ssXXX").alias("update_ts"),
        F.to_timestamp("reading_update_timestamp", "yyyy-MM-dd'T'HH:mm:ssXXX").alias("reading_update_ts"),
        F.trim("station_id").alias("station_id"),
        F.trim("station_name").alias("station_name"),
        F.trim("station_device_id").alias("station_device_id"),
        F.col("location_longitude").cast("double").alias("longitude"),
        F.col("location_latitude").cast("double").alias("latitude"),
        F.col("reading_value").cast("double").alias("rainfall_mm"),
        F.trim("reading_type").alias("reading_type"),
        F.trim("reading_unit").alias("reading_unit"),
    )


def valid_rows(parsed: DataFrame) -> tuple[DataFrame, DataFrame]:
    valid = (
        F.col("observation_ts").isNotNull()
        & F.col("station_id").isNotNull()
        & (F.length("station_id") > 0)
        & F.col("rainfall_mm").isNotNull()
        & (F.col("rainfall_mm") >= 0)
        & F.col("longitude").between(103.0, 105.0)
        & F.col("latitude").between(1.0, 2.0)
        & (F.col("reading_unit") == "mm")
    )
    return parsed.filter(valid), parsed.filter(~valid)


def deduplicate(valid: DataFrame) -> tuple[DataFrame, DataFrame]:
    ordering = Window.partitionBy("station_id", "observation_ts").orderBy(
        F.col("update_ts").desc_nulls_last(), F.col("reading_update_ts").desc_nulls_last()
    )
    ranked = valid.withColumn("_dedup_rank", F.row_number().over(ordering))
    return ranked.filter("_dedup_rank = 1").drop("_dedup_rank"), ranked.filter("_dedup_rank > 1")


def gap_summary(cleaned: DataFrame) -> list[dict[str, object]]:
    prior = Window.partitionBy("station_id").orderBy("observation_ts")
    gaps = (
        cleaned.select("station_id", "observation_ts")
        .withColumn("previous_ts", F.lag("observation_ts").over(prior))
        .withColumn("gap_seconds", F.unix_timestamp("observation_ts") - F.unix_timestamp("previous_ts"))
        .filter(F.col("gap_seconds") > 300)
        .groupBy("station_id")
        .agg(
            F.count("*").alias("gap_events"),
            F.sum((F.col("gap_seconds") / 300 - 1).cast("long")).alias("missing_five_minute_intervals"),
            F.max("gap_seconds").alias("max_gap_seconds"),
        )
        .orderBy("station_id")
    )
    return [row.asDict(recursive=True) for row in gaps.collect()]


def quality_report(parsed: DataFrame, invalid: DataFrame, duplicates: DataFrame, cleaned: DataFrame) -> dict[str, object]:
    counts = {
        "rows_read": parsed.count(),
        "rows_invalid": invalid.count(),
        "rows_duplicate_discarded": duplicates.count(),
        "rows_retained": cleaned.count(),
    }
    date_mismatches = cleaned.filter(F.to_date("observation_ts").cast("string") != F.col("source_date")).count()
    invalid_reasons = invalid.select(
        F.sum(F.col("observation_ts").isNull().cast("long")).alias("unparseable_observation_timestamp"),
        F.sum((F.col("station_id").isNull() | (F.length("station_id") == 0)).cast("long")).alias("missing_station_id"),
        F.sum((F.col("rainfall_mm").isNull() | (F.col("rainfall_mm") < 0)).cast("long")).alias("invalid_rainfall_mm"),
        F.sum((~F.col("longitude").between(103.0, 105.0) | ~F.col("latitude").between(1.0, 2.0)).cast("long")).alias("invalid_coordinates"),
        F.sum((F.col("reading_unit") != "mm").cast("long")).alias("unexpected_unit"),
    ).first().asDict()
    return {
        "counts": counts,
        "invalid_reason_counts": {key: value or 0 for key, value in invalid_reasons.items()},
        "date_timestamp_mismatches": date_mismatches,
        "stations": cleaned.select("station_id").distinct().count(),
        "observation_start_sgt": str(cleaned.agg(F.min("observation_ts")).first()[0]),
        "observation_end_sgt": str(cleaned.agg(F.max("observation_ts")).first()[0]),
        "station_gaps_over_five_minutes": gap_summary(cleaned),
    }


def clean(paths: CleanPaths, years: list[int], spark: SparkSession) -> dict[str, object]:
    parsed = parse_raw(spark, raw_paths(paths.raw_dir, years))
    valid, invalid = valid_rows(parsed)
    cleaned, duplicates = deduplicate(valid)
    cleaned = cleaned.withColumn("year", F.year("observation_ts"))

    report = quality_report(parsed, invalid, duplicates, cleaned)
    report["years_requested"] = years
    report["output"] = asdict(paths)

    (
        cleaned.write.mode("overwrite")
        .partitionBy("year")
        .parquet(str(paths.output_dir))
    )
    paths.report_path.parent.mkdir(parents=True, exist_ok=True)
    paths.report_path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report
