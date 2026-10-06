"""Leakage-safe multi-station spatial features for rainfall nowcasting."""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Iterable

from pyspark.sql import DataFrame, SparkSession, functions as F


SPATIAL_NUMERIC_FEATURES = [
    "neighbor_count_available",
    "neighbor_weight_available",
    "neighbor_min_distance_km_available",
    "neighbor_rainfall_last_5m_mm_idw_mean",
    "neighbor_rainfall_last_15m_mm_idw_mean",
    "neighbor_rainfall_last_30m_mm_idw_mean",
    "neighbor_rainfall_last_60m_mm_idw_mean",
    "neighbor_rainfall_last_30m_mm_max",
    "neighbor_raining_fraction_5m",
]

_NEIGHBOR_VALUE_COLUMNS = [
    "rainfall_last_5m_mm",
    "rainfall_last_15m_mm",
    "rainfall_last_30m_mm",
    "rainfall_last_60m_mm",
]


def _distance_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Great-circle distance; stable enough for the small Singapore area."""
    radius_km = 6371.0088
    delta_lat = radians(lat_b - lat_a)
    delta_lon = radians(lon_b - lon_a)
    haversine = sin(delta_lat / 2) ** 2 + cos(radians(lat_a)) * cos(radians(lat_b)) * sin(delta_lon / 2) ** 2
    return 2 * radius_km * asin(sqrt(haversine))


def build_neighbor_map(
    spark: SparkSession, locations: Iterable[dict[str, object]], neighbor_count: int
) -> DataFrame:
    """Build a small directed K-nearest-station map on the driver.

    Station coordinates are static metadata and the number of stations is small,
    so collecting this relation avoids an expensive all-pairs Spark join.
    """
    points = sorted(
        (
            {
                "station_id": str(row["station_id"]),
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
            }
            for row in locations
        ),
        key=lambda point: point["station_id"],
    )
    if len(points) <= neighbor_count:
        raise ValueError(f"need more than {neighbor_count} stations, found {len(points)}")
    rows: list[tuple[str, str, int, float, float]] = []
    for target in points:
        candidates = sorted(
            (
                (
                    _distance_km(target["latitude"], target["longitude"], source["latitude"], source["longitude"]),
                    source["station_id"],
                )
                for source in points
                if source["station_id"] != target["station_id"]
            ),
            key=lambda item: (item[0], item[1]),
        )[:neighbor_count]
        for rank, (distance_km, source_id) in enumerate(candidates, start=1):
            rows.append((target["station_id"], source_id, rank, distance_km, 1.0 / max(distance_km, 0.05)))
    return spark.createDataFrame(
        rows,
        "target_station_id string, neighbor_station_id string, neighbor_rank int, distance_km double, inverse_distance_weight double",
    )


def canonical_slot(frame: DataFrame, timestamp_column: str = "prediction_ts") -> DataFrame:
    """Assign a five-minute slot by rounding, reconciling :00 and :59 exports."""
    return frame.withColumn(
        "_spatial_slot_epoch",
        (F.round(F.unix_timestamp(timestamp_column) / F.lit(300)) * F.lit(300)).cast("long"),
    )


def add_lagged_neighbor_features(base: DataFrame, neighbors: DataFrame) -> DataFrame:
    """Add features from K nearest stations, ending at least one slot before t.

    The one-slot delay means a source record can never be later than the target
    record, including when exporters disagree by one second at a nominal slot.
    Missing neighbours are represented by availability features plus zero-filled
    aggregate values, never silently interpreted as observed zero rainfall.
    """
    slotted = canonical_slot(base)
    targets = slotted.select("station_id", "prediction_ts", "_spatial_slot_epoch").alias("target")
    source_columns = [
        F.col("station_id").alias("neighbor_station_id"),
        F.col("_spatial_slot_epoch").alias("source_slot_epoch"),
        *[F.col(column).alias(f"neighbor_{column}") for column in _NEIGHBOR_VALUE_COLUMNS],
    ]
    sources = slotted.select(*source_columns).alias("source")
    expanded = (
        targets.join(F.broadcast(neighbors).alias("map"), F.col("target.station_id") == F.col("map.target_station_id"), "left")
        .join(
            sources,
            (F.col("map.neighbor_station_id") == F.col("source.neighbor_station_id"))
            & (F.col("source.source_slot_epoch") == F.col("target._spatial_slot_epoch") - F.lit(300)),
            "left",
        )
    )
    available = F.col("source.neighbor_rainfall_last_5m_mm").isNotNull()
    weighted_mean_columns = []
    for column in _NEIGHBOR_VALUE_COLUMNS:
        source_column = F.col(f"source.neighbor_{column}")
        weighted_mean_columns.append(
            (
                F.sum(F.when(available, source_column * F.col("map.inverse_distance_weight")))
                / F.sum(F.when(available, F.col("map.inverse_distance_weight")))
            ).alias(f"neighbor_{column}_idw_mean")
        )
    aggregates = expanded.groupBy(
        F.col("target.station_id").alias("station_id"), F.col("target.prediction_ts").alias("prediction_ts")
    ).agg(
        F.sum(available.cast("int")).alias("neighbor_count_available"),
        F.coalesce(F.sum(F.when(available, F.col("map.inverse_distance_weight"))), F.lit(0.0)).alias("neighbor_weight_available"),
        F.min(F.when(available, F.col("map.distance_km"))).alias("neighbor_min_distance_km_available"),
        *weighted_mean_columns,
        F.max(F.col("source.neighbor_rainfall_last_30m_mm")).alias("neighbor_rainfall_last_30m_mm_max"),
        F.avg(F.when(available, (F.col("source.neighbor_rainfall_last_5m_mm") > 0).cast("double"))).alias("neighbor_raining_fraction_5m"),
    )
    joined = base.join(aggregates, on=["station_id", "prediction_ts"], how="left")
    return joined.fillna(0.0, subset=SPATIAL_NUMERIC_FEATURES)
