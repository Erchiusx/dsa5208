"""Additional leakage-safe predictors keyed by (station_id, nominal five-minute slot).

They are joined onto `spatial_features_<year>` without changing its eligible rows:
  * own station on exact slot windows (t-11..t is 60 min, etc.): current and lagged
    readings, 15/30/60-min and 3-h sums, 60-min peak, 3-h data completeness;
  * each of the 8 nearest stations active in the year, lagged one slot like spatial.py:
    latest reading, 15-min sum and availability;
  * storm geometry from those neighbours: the rain-weighted centroid offset (km) of the
    last 15 min and of the 15 min before, its displacement, and its radial approach;
  * minute-of-day and day-of-year cycles.
"""
from __future__ import annotations

import math
from functools import reduce
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window, functions as F

from rainfall_project.spatial import _distance_km

K = 8
SLOT = 300
NO_RAIN_RADIUS_KM = 20.0  # sentinel distance when no neighbour is raining

OWN = ["own_y0", "own_lag1", "own_lag2", "own_s3", "own_s6", "own_s12", "own_max12", "own_s36", "own_c36_frac"]
PER_NEIGHBOUR = [f"nb{k}_{v}" for k in range(1, K + 1) for v in ("y1", "s3", "avail")]
GEOMETRY = ["nb_s12_max", "nb_s36_idw", "nb_nearest_wet_km", "storm_cx_now", "storm_cy_now", "storm_cx_prev",
            "storm_cy_prev", "storm_dx", "storm_dy", "storm_r_now", "storm_dr"]
CALENDAR = ["tod_sin", "tod_cos", "doy_sin", "doy_cos"]
RICH_FEATURES = [*OWN, *PER_NEIGHBOUR, *GEOMETRY, *CALENDAR]


def slot_of(ts_col: str) -> F.Column:
    return (F.round(F.unix_timestamp(ts_col) / F.lit(SLOT)) * F.lit(SLOT)).cast("long")


def station_slots(cleaned: DataFrame) -> DataFrame:
    """One reading per (station, nominal slot); the latest export wins, as in spatial.py."""
    w = Window.partitionBy("station_id", "slot").orderBy(F.col("observation_ts").desc())
    return (cleaned.select("station_id", "observation_ts", "rainfall_mm", "latitude", "longitude")
            .withColumn("slot", slot_of("observation_ts"))
            .withColumn("_r", F.row_number().over(w)).filter("_r = 1").drop("_r"))


def window_features(slots: DataFrame) -> DataFrame:
    o = Window.partitionBy("station_id").orderBy("slot")
    rng = lambda a, b: o.rangeBetween(a * SLOT, b * SLOT)  # noqa: E731
    y = F.col("rainfall_mm")
    return slots.select(
        "station_id", "slot", y.alias("y0"),
        F.sum(y).over(rng(-1, -1)).alias("lag1"), F.sum(y).over(rng(-2, -2)).alias("lag2"),
        F.sum(y).over(rng(-2, 0)).alias("s3"), F.sum(y).over(rng(-5, 0)).alias("s6"),
        F.sum(y).over(rng(-11, 0)).alias("s12"), F.max(y).over(rng(-11, 0)).alias("max12"),
        F.count(y).over(rng(-11, 0)).alias("c12"),
        F.sum(y).over(rng(-35, 0)).alias("s36"), F.count(y).over(rng(-35, 0)).alias("c36"),
    )


def neighbour_map(spark: SparkSession, slots: DataFrame) -> DataFrame:
    """8 nearest other stations among those reporting in this year, with offsets in km."""
    pts = slots.groupBy("station_id").agg(F.avg("latitude").alias("lat"), F.avg("longitude").alias("lon")).collect()
    rows = []
    for t in pts:
        cand = sorted(((_distance_km(t["lat"], t["lon"], s["lat"], s["lon"]), s["station_id"], s) for s in pts
                       if s["station_id"] != t["station_id"]), key=lambda c: (c[0], c[1]))[:K]
        for k, (d, sid, s) in enumerate(cand, start=1):
            dx = (s["lon"] - t["lon"]) * 111.32 * math.cos(math.radians(t["lat"]))
            dy = (s["lat"] - t["lat"]) * 111.32
            rows.append((t["station_id"], k, sid, d, dx, dy))
    return spark.createDataFrame(rows, "station_id string, k int, nb_station string, dist double, dx double, dy double")


def build_year(spark: SparkSession, interim_dir: Path, year: int) -> DataFrame:
    cur = spark.read.parquet(str(interim_dir / f"cleaned_rainfall_{year}"))
    frames = [cur]
    prev_dir = interim_dir / f"cleaned_rainfall_{year - 1}"
    if prev_dir.exists():  # 3-hour windows at 1 January need the end of the previous year
        frames.append(spark.read.parquet(str(prev_dir))
                      .filter(F.col("observation_ts") >= F.to_timestamp(F.lit(f"{year - 1}-12-31 00:00:00"))))
    slots = station_slots(reduce(lambda a, b: a.unionByName(b, allowMissingColumns=True), frames))
    wf = window_features(slots).cache()
    nbm = neighbour_map(spark, slots.filter(F.year(F.from_unixtime("slot")) == year))

    src = wf.select(F.col("station_id").alias("nb_station"), (F.col("slot") + SLOT).alias("slot"),
                    F.col("y0").alias("v_y1"), F.col("s3").alias("v_s3"), (F.col("s6") - F.col("s3")).alias("v_prev3"),
                    F.col("s12").alias("v_s12"), F.col("s36").alias("v_s36"))
    targets = wf.select("station_id", "slot").filter(F.year(F.from_unixtime("slot")) == year)
    ex = targets.join(F.broadcast(nbm), "station_id").join(src, ["nb_station", "slot"], "left")
    have = F.col("v_y1").isNotNull()
    s3, prev3 = F.coalesce("v_s3", F.lit(0.0)), F.coalesce("v_prev3", F.lit(0.0))
    idw = F.lit(1.0) / F.greatest("dist", F.lit(0.05))
    per_k = []
    for k in range(1, K + 1):
        per_k += [F.max(F.when(F.col("k") == k, F.col("v_y1"))).alias(f"nb{k}_y1"),
                  F.max(F.when(F.col("k") == k, F.col("v_s3"))).alias(f"nb{k}_s3"),
                  F.max(F.when((F.col("k") == k) & have, F.lit(1.0))).alias(f"nb{k}_avail")]
    agg = ex.groupBy("station_id", "slot").agg(
        *per_k,
        F.max("v_s12").alias("nb_s12_max"),
        (F.sum(F.when(have, F.col("v_s36") * idw)) / F.sum(F.when(have, idw))).alias("nb_s36_idw"),
        F.min(F.when(s3 > 0, F.col("dist"))).alias("nb_nearest_wet_km"),
        F.sum(s3).alias("_w_now"), F.sum(s3 * F.col("dx")).alias("_x_now"), F.sum(s3 * F.col("dy")).alias("_y_now"),
        F.sum(prev3).alias("_w_prev"), F.sum(prev3 * F.col("dx")).alias("_x_prev"), F.sum(prev3 * F.col("dy")).alias("_y_prev"),
    )
    safe = lambda num, den: F.when(F.col(den) > 0, F.col(num) / F.col(den)).otherwise(F.lit(0.0))  # noqa: E731
    radius = lambda x, y, w: F.when(F.col(w) > 0, F.sqrt(F.col(x) ** 2 + F.col(y) ** 2)).otherwise(F.lit(NO_RAIN_RADIUS_KM))  # noqa: E731
    agg = (agg.withColumn("storm_cx_now", safe("_x_now", "_w_now")).withColumn("storm_cy_now", safe("_y_now", "_w_now"))
           .withColumn("storm_cx_prev", safe("_x_prev", "_w_prev")).withColumn("storm_cy_prev", safe("_y_prev", "_w_prev"))
           .withColumn("storm_r_now", radius("storm_cx_now", "storm_cy_now", "_w_now"))
           .withColumn("_r_prev", radius("storm_cx_prev", "storm_cy_prev", "_w_prev"))
           .withColumn("both", (F.col("_w_now") > 0) & (F.col("_w_prev") > 0))
           .withColumn("storm_dx", F.when(F.col("both"), F.col("storm_cx_now") - F.col("storm_cx_prev")).otherwise(0.0))
           .withColumn("storm_dy", F.when(F.col("both"), F.col("storm_cy_now") - F.col("storm_cy_prev")).otherwise(0.0))
           .withColumn("storm_dr", F.col("storm_r_now") - F.col("_r_prev"))
           .drop("_w_now", "_x_now", "_y_now", "_w_prev", "_x_prev", "_y_prev", "_r_prev", "both"))

    sgt = F.col("slot") + F.lit(8 * 3600)
    own = wf.filter(F.year(F.from_unixtime("slot")) == year).select(
        "station_id", "slot",
        F.col("y0").alias("own_y0"), F.col("lag1").alias("own_lag1"), F.col("lag2").alias("own_lag2"),
        F.col("s3").alias("own_s3"), F.col("s6").alias("own_s6"), F.col("s12").alias("own_s12"),
        F.col("max12").alias("own_max12"), F.col("s36").alias("own_s36"), (F.col("c36") / 36.0).alias("own_c36_frac"),
        F.sin(2 * math.pi * (sgt % 86400) / 86400).alias("tod_sin"), F.cos(2 * math.pi * (sgt % 86400) / 86400).alias("tod_cos"),
        F.sin(2 * math.pi * F.dayofyear(F.from_unixtime("slot")) / 365.25).alias("doy_sin"),
        F.cos(2 * math.pi * F.dayofyear(F.from_unixtime("slot")) / 365.25).alias("doy_cos"),
    )
    out = own.join(agg, ["station_id", "slot"], "left")
    fill = {c: 0.0 for c in RICH_FEATURES if c != "nb_nearest_wet_km"}
    return out.fillna(fill).fillna({"nb_nearest_wet_km": NO_RAIN_RADIUS_KM})


def with_rich_features(spatial: DataFrame, rich: DataFrame) -> DataFrame:
    """Attach rich predictors to spatial_features rows; eligibility is unchanged."""
    return (spatial.withColumn("slot", slot_of("prediction_ts"))
            .join(rich, ["station_id", "slot"], "left")
            .fillna({c: 0.0 for c in RICH_FEATURES if c != "nb_nearest_wet_km"})
            .fillna({"nb_nearest_wet_km": NO_RAIN_RADIUS_KM}))
