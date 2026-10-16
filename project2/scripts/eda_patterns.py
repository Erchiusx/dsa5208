#!/usr/bin/env python3
"""Task 1: reduce the QC'd five-minute readings to the tables behind the weather-pattern figures.

Spark turns the 48 M readings into station-hours and rain events, which are kept as Parquet under
data/interim/eda/. It then writes small summary tables as CSV to reports/eda/, and
scripts/plot_eda.py draws the figures from those CSVs only.

A reading stamped t holds the rain of (t - 5 min, t], so it is attributed to the hour and day
that contain t - 5 min. Rates are computed over observed time, so a station's gaps lower its weight,
not its totals. Seasons follow the Meteorological Service Singapore calendar: NE monsoon Dec-Mar,
inter-monsoon Apr-May, SW monsoon Jun-Sep, inter-monsoon Oct-Nov.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pyspark.sql import DataFrame, Window, functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import build_spark  # noqa: E402
from rainfall_project.datasets import load_years  # noqa: E402
from rainfall_project.qc import read_cleaned, station_slots  # noqa: E402
from rainfall_project.ziln import eligible  # noqa: E402

YEARS = list(range(2017, 2025))
SLOT, HOUR = 300, 3600
EVENT_GAP_S = HOUR  # wet readings more than one dry hour apart belong to different events
DURATION_BINS_MIN = [15, 60, 180, 360]  # event classes: <=15 min, <=1 h, <=3 h, <=6 h, > 6 h
DEPTH_BINS_MM = [0.5, 1, 2, 5, 10, 20, 50]
LAST30_BINS_MM = [0.0, 1.0, 5.0]  # 30-min history classes: 0, (0, 1], (1, 5], > 5


def season(month: str) -> F.Column:
    m = F.col(month)
    return (F.when(m.isin(12, 1, 2, 3), "NEM").when(m.isin(4, 5), "IM1")
            .when(m.isin(6, 7, 8, 9), "SWM").otherwise("IM2"))


def bucket(col: F.Column, edges: list[float]) -> F.Column:
    """Number of edges strictly below col: class k is (edges[k-1], edges[k]]."""
    return sum((col > F.lit(e)).cast("int") for e in edges)


def calendar(frame: DataFrame, epoch: str) -> DataFrame:
    ts = F.timestamp_seconds(F.col(epoch))
    return (frame.withColumn("date", F.to_date(ts)).withColumn("year", F.year(ts)).withColumn("month", F.month(ts))
            .withColumn("hod", F.hour(ts)).withColumn("season", season("month")))


def hourly_table(slots: DataFrame) -> DataFrame:
    """(station_id, hour_start, n, rain, wet, max5) with the SGT calendar of the hour."""
    h = (slots.withColumn("hour_start", F.floor((F.col("qc_slot") - SLOT) / HOUR) * HOUR)
         .groupBy("station_id", "hour_start")
         .agg(F.count("*").alias("n"), F.round(F.sum("y"), 3).alias("rain"),
              F.sum((F.col("y") > 0).cast("int")).alias("wet"), F.max("y").alias("max5")))
    return calendar(h, "hour_start")


def event_table(slots: DataFrame) -> DataFrame:
    """Rain events per station: wet readings chained while less than EVENT_GAP_S apart.

    `complete` says whether every slot from the first to the last wet reading was observed
    (row numbers over all of a station's readings count the observed slots in between)."""
    by_station = Window.partitionBy("station_id").orderBy("qc_slot")
    wet = (slots.withColumn("rn", F.row_number().over(by_station)).filter(F.col("y") > 0)
           .withColumn("gap", F.col("qc_slot") - F.lag("qc_slot").over(by_station)))
    wet = wet.withColumn("event", F.sum((F.col("gap").isNull() | (F.col("gap") > EVENT_GAP_S + SLOT)).cast("long"))
                         .over(by_station.rowsBetween(Window.unboundedPreceding, 0)))
    ev = (wet.groupBy("station_id", "event")
          .agg(F.min("qc_slot").alias("first"), F.max("qc_slot").alias("last"), F.round(F.sum("y"), 3).alias("depth"),
               F.max("y").alias("peak5"), F.count("*").alias("n_wet"), (F.max("rn") - F.min("rn") + 1).alias("n_obs"))
          .withColumn("duration_min", (F.col("last") - F.col("first")) / 60 + 5)
          .withColumn("complete", F.col("n_obs") == (F.col("last") - F.col("first")) / SLOT + 1)
          .withColumn("start", F.col("first") - SLOT))
    return calendar(ev, "start").withColumn("hod_start", F.col("hod")).drop("hod")


def pair_correlation(table: DataFrame, time_col: str, stations: DataFrame, scale: str) -> DataFrame:
    """Pearson correlation of station totals for every station pair and season (pairs observed together)."""
    a = table.select("station_id", time_col, "season", F.col("rain").alias("x"))
    b = table.select(F.col("station_id").alias("sb"), time_col, F.col("rain").alias("z"))
    s = (a.join(b, time_col).filter(F.col("station_id") < F.col("sb"))
         .groupBy("station_id", "sb", "season")
         .agg(F.count("*").alias("n"), F.sum("x").alias("sx"), F.sum("z").alias("sz"), F.sum(F.col("x") * F.col("z")).alias("sxz"),
              F.sum(F.col("x") ** 2).alias("sxx"), F.sum(F.col("z") ** 2).alias("szz")))
    cov = F.col("n") * F.col("sxz") - F.col("sx") * F.col("sz")
    var = (F.col("n") * F.col("sxx") - F.col("sx") ** 2) * (F.col("n") * F.col("szz") - F.col("sz") ** 2)
    pos = stations.select("station_id", F.col("lat").alias("la"), F.col("lon").alias("lo"))
    posb = stations.select(F.col("station_id").alias("sb"), F.col("lat").alias("lb"), F.col("lon").alias("lob"))
    km = 6371.0 * 2 * F.asin(F.sqrt(F.sin(F.radians(F.col("lb") - F.col("la")) / 2) ** 2 + F.cos(F.radians("la")) * F.cos(F.radians("lb"))
                                   * F.sin(F.radians(F.col("lob") - F.col("lo")) / 2) ** 2))
    return (s.withColumn("corr", F.try_divide(cov, F.sqrt(var))).join(pos, "station_id").join(posb, "sb")  # null: a constant series
            .select(F.lit(scale).alias("scale"), F.col("station_id").alias("station_a"), F.col("sb").alias("station_b"),
                    "season", "n", F.round(km, 3).alias("dist_km"), F.round("corr", 5).alias("corr")))


def write_csv(frame: DataFrame, out_dir: Path, name: str, only: set[str] | None = None) -> None:
    if only and name not in only and (out_dir / f"{name}.csv").exists():
        return
    pdf = frame.toPandas()
    pdf.to_csv(out_dir / f"{name}.csv", index=False)
    print(f"{name}.csv: {len(pdf):,} rows", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interim-dir", type=Path, default=PROJECT_DIR / "data" / "interim_qc", help="QC'd readings")
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_DIR / "data" / "processed_qc")
    parser.add_argument("--work-dir", type=Path, default=PROJECT_DIR / "data" / "interim" / "eda")
    parser.add_argument("--out-dir", type=Path, default=PROJECT_DIR / "reports" / "eda")
    parser.add_argument("--tables", nargs="*", help="recompute only these CSVs (missing ones are always written)")
    args = parser.parse_args()
    only = set(args.tables or [])
    args.out_dir.mkdir(parents=True, exist_ok=True)

    spark = build_spark("dsa5208-rainfall-eda")
    spark.sparkContext.setLogLevel("ERROR")
    try:
        def write(frame: DataFrame, name: str) -> None:
            write_csv(frame, args.out_dir, name, only)

        def materialise(name: str, build) -> DataFrame:
            path = args.work_dir / name
            if not (path / "_SUCCESS").exists():
                build().write.mode("overwrite").parquet(str(path))
            return spark.read.parquet(str(path))

        readings = read_cleaned(spark, args.interim_dir, YEARS)
        stations = (readings.groupBy("station_id")
                    .agg(F.max("station_name").alias("name"), F.avg("longitude").alias("lon"), F.avg("latitude").alias("lat"),
                         F.stddev("longitude").alias("lon_sd"), F.stddev("latitude").alias("lat_sd"),
                         F.min(F.year("observation_ts")).alias("first_year"), F.max(F.year("observation_ts")).alias("last_year"))
                    .cache())
        write(stations.orderBy("station_id"), "stations")
        slots = station_slots(readings).withColumn("y", F.round("y", 3))  # 2024 readings carry float32 noise
        hourly = materialise("hourly", lambda: hourly_table(slots)).cache()
        events = materialise("events", lambda: event_table(slots)).cache()

        # coverage and monthly station statistics. Wet-slot frequency and rain per wet slot are unbiased
        # under readings missing at random; wet-hour statistics need complete hours, which March 2018 lacks
        write(hourly.groupBy("station_id", "year").agg(F.sum("n").alias("slots")).orderBy("station_id", "year"), "coverage")
        complete = F.col("n") == 12
        write(hourly.groupBy("station_id", "year", "month")
              .agg(F.sum("n").alias("slots"), F.round(F.sum("rain"), 3).alias("rain"), F.sum("wet").alias("wet_slots"),
                   F.sum(complete.cast("int")).alias("complete_hours"),
                   F.sum((complete & (F.col("rain") > 0)).cast("int")).alias("wet_hours"),
                   F.round(F.sum(F.when(complete, F.col("rain"))), 3).alias("rain_complete"),
                   F.max("rain").alias("max_hour"), F.max("max5").alias("max5"))
              .orderBy("station_id", "year", "month"), "station_month")
        write(hourly.groupBy("year", "month", "hod")
              .agg(F.sum("n").alias("slots"), F.sum("wet").alias("wet_slots"), F.round(F.sum("rain"), 3).alias("rain"),
                   F.sum(complete.cast("int")).alias("hours"), F.sum((complete & (F.col("rain") > 0)).cast("int")).alias("wet_hours"),
                   F.sum((F.col("rain") > 10).cast("int")).alias("hours_gt10"))
              .orderBy("year", "month", "hod"), "diurnal")

        # station-day totals for extremes and spatial correlation (days with >= 95 % of slots observed)
        daily = (hourly.groupBy("station_id", "date").agg(F.sum("n").alias("n"), F.round(F.sum("rain"), 3).alias("rain"))
                 .filter(F.col("n") >= 0.95 * 288).withColumn("month", F.month("date")).withColumn("season", season("month"))
                 .withColumn("year", F.year("date")).cache())
        write(hourly.groupBy("station_id", "year")
              .agg(F.max("rain").alias("max_hour"), F.max("max5").alias("max5"),
                   *[F.sum((F.col("rain") > t).cast("int")).alias(f"hours_gt{t}") for t in (10, 20, 40)])
              .join(daily.groupBy("station_id", "year").agg(F.max("rain").alias("max_day"), F.count("*").alias("complete_days"),
                                                            F.sum((F.col("rain") >= 1).cast("int")).alias("rain_days")),
                    ["station_id", "year"], "left")
              .orderBy("station_id", "year"), "extremes")
        pos = stations.select("station_id", "lat", "lon")
        corr = pair_correlation(daily, "date", pos, "day").unionByName(
            pair_correlation(hourly.filter(complete), "hour_start", pos, "hour"))
        write(corr.orderBy("scale", "season", "station_a", "station_b"), "pair_correlation")

        # rain events (only those whose span was fully observed)
        ev = events.filter("complete").withColumn("dur_class", bucket(F.col("duration_min"), DURATION_BINS_MIN))
        write(ev.groupBy("year", "month", "dur_class")
              .agg(F.count("*").alias("events"), F.round(F.sum("depth"), 3).alias("rain"))
              .orderBy("year", "month", "dur_class"), "events_by_month")
        write(ev.withColumn("depth_class", bucket(F.col("depth"), DEPTH_BINS_MM))
              .groupBy("season", "hod_start", "dur_class", "depth_class")
              .agg(F.count("*").alias("events"), F.round(F.sum("depth"), 3).alias("rain"),
                   F.round(F.sum("duration_min"), 1).alias("minutes"), F.round(F.sum("peak5"), 3).alias("sum_peak5"))
              .orderBy("season", "hod_start", "dur_class", "depth_class"), "events_by_class")
        write(events.groupBy("complete").agg(F.count("*").alias("events"), F.round(F.sum("depth"), 1).alias("rain")),
              "events_completeness")

        # 30-minute persistence: P(next 30 min > r) given the last 30 min, by season and hour of day
        feats = eligible(load_years(spark, args.processed_dir, YEARS, "spatial"))
        last = F.round("rainfall_last_30m_mm", 3)
        write(feats.withColumn("month", F.month("prediction_ts")).withColumn("season", season("month"))
              .withColumn("hod", F.hour("prediction_ts")).withColumn("last30_class", bucket(last, LAST30_BINS_MM))
              .groupBy("season", "hod", "last30_class")
              .agg(F.count("*").alias("rows"), *[F.sum((F.col("y") > r).cast("long")).alias(f"gt{r:g}") for r in (0.2, 1, 5, 10)])
              .orderBy("season", "hod", "last30_class"), "persistence")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
