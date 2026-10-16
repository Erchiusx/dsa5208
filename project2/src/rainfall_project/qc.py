"""Rule-based quality control (QC) of the cleaned five-minute gauge readings.

Every rule compares a station only with its own readings and with its neighbours'
readings (never with model output), and the same thresholds are applied to every year.

Conventions
  * readings are aligned to the nominal five-minute slot (as spatial.py / rich_features.py);
    one reading per (station, slot), the latest export wins;
  * a reading stamped at slot t is the total for (t - 5 min, t], so it belongs to the
    hour floor((t - 5 min) / 1 h) and to the SGT day of that hour;
  * neighbours of a station are the other stations within `radius_km`. For a station-day
    the neighbour totals are *hour-matched*: neighbour j's total counts only the hours in
    which the station itself reported, and j is used only if it reported in at least
    `hour_cover` of those hours. The `neighbour_count` nearest such stations are used.

Rules (thresholds in QCConfig)
  A  stuck_zero      a run of consecutive station-days with data and an exact-zero total
                     (days without data do not break the run) is masked whole when it
                     contains >= 3 days on which the hour-matched neighbour median was >= 5 mm.
  B  isolated_extreme station-day total >= 100 mm while the wettest hour-matched neighbour
                     received < 15 % of it.
  C  phantom_rain    station-day total >= 20 mm, >= 1 mm in at least 3 different hours,
                     while the wettest of >= 5 hour-matched neighbours received <= 5 % of it.
  D  repeat          >= 3 days flagged by B/C at one station, consecutive flags at most 30 days
                     apart: the whole span from the first to the last of them is masked.
  E  spike           a single five-minute value >= 5 mm whose own previous and next readings
                     are both < 10 % of it, while no neighbour within 10 km (>= 3 reporting)
                     has a reading >= 1 mm within +-30 min. Only that slot is masked.
B, C and D masks are widened by one day on each side (faults rarely start or stop at midnight).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import reduce
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window, functions as F

from rainfall_project.spatial import _distance_km

SLOT = 300
HOUR = 3600


@dataclass(frozen=True)
class QCConfig:
    radius_km: float = 10.0
    neighbour_count: int = 8
    hour_cover: float = 0.8
    # A: stuck zero
    stuck_wet_median_mm: float = 5.0
    stuck_min_neighbours: int = 3
    stuck_min_wet_days: int = 3
    # B: isolated extreme day
    extreme_total_mm: float = 100.0
    extreme_ratio: float = 0.15
    extreme_min_neighbours: int = 3
    # C: phantom rain day
    phantom_total_mm: float = 20.0
    phantom_ratio: float = 0.05
    phantom_hour_mm: float = 1.0
    phantom_min_hours: int = 3
    phantom_min_neighbours: int = 5
    # D: repeated B/C flags
    repeat_min_days: int = 3
    repeat_max_gap_days: int = 30
    day_buffer: int = 1
    # E: single-slot spike
    spike_mm: float = 5.0
    spike_adjacent_ratio: float = 0.1
    spike_neighbour_mm: float = 1.0
    spike_window_slots: int = 6
    spike_min_neighbours: int = 3


def read_cleaned(spark: SparkSession, interim_dir: Path, years: list[int]) -> DataFrame:
    frames = [spark.read.parquet(str(interim_dir / f"cleaned_rainfall_{y}")) for y in years]
    return reduce(lambda a, b: a.unionByName(b, allowMissingColumns=True), frames)


def with_slot_and_day(frame: DataFrame) -> DataFrame:
    """Add the nominal slot (epoch s) and the SGT day of the reading's accumulation hour."""
    slot = (F.round(F.unix_timestamp("observation_ts") / F.lit(SLOT)) * F.lit(SLOT)).cast("long")
    return (frame.withColumn("qc_slot", slot)
            .withColumn("qc_day", F.to_date(F.from_unixtime(F.floor((F.col("qc_slot") - SLOT) / HOUR) * HOUR))))


def station_slots(cleaned: DataFrame) -> DataFrame:
    """(station_id, qc_slot, qc_day, y): one reading per station and slot, the latest export wins."""
    w = Window.partitionBy("station_id", "qc_slot").orderBy(F.col("observation_ts").desc())
    return (with_slot_and_day(cleaned.select("station_id", "observation_ts", "rainfall_mm"))
            .withColumn("_r", F.row_number().over(w)).filter("_r = 1")
            .select("station_id", "qc_slot", "qc_day", F.col("rainfall_mm").alias("y")))


def neighbour_pairs(spark: SparkSession, cleaned: DataFrame, radius_km: float) -> tuple[DataFrame, list[dict]]:
    """All ordered station pairs within radius_km, ranked by distance (static coordinates)."""
    pts = cleaned.groupBy("station_id").agg(F.avg("latitude").alias("lat"), F.avg("longitude").alias("lon")).collect()
    rows = []
    for t in pts:
        cand = sorted(((_distance_km(t["lat"], t["lon"], s["lat"], s["lon"]), s["station_id"]) for s in pts
                       if s["station_id"] != t["station_id"]), key=lambda c: (c[0], c[1]))
        rows += [(t["station_id"], sid, k, d) for k, (d, sid) in enumerate(cand, start=1) if d <= radius_km]
    pairs = spark.createDataFrame(rows, "station_id string, nb string, nb_rank int, dist double")
    return pairs, [{"station_id": r[0], "nb": r[1], "rank": r[2], "dist_km": round(r[3], 3)} for r in rows]


def daily_table(slots: DataFrame, pairs: DataFrame, cfg: QCConfig) -> DataFrame:
    """Own daily statistics plus hour-matched statistics of the nearest available neighbours."""
    hourly = (slots.withColumn("hour", F.floor((F.col("qc_slot") - SLOT) / HOUR))
              .groupBy("station_id", "hour", "qc_day")
              .agg(F.count("*").alias("n"), F.sum("y").alias("tot"),
                   F.sum((F.col("y") > 0).cast("int")).alias("wet"), F.max("y").alias("mx"))).cache()
    own = hourly.groupBy("station_id", "qc_day").agg(
        F.sum("n").alias("n_slots"), F.count("*").alias("n_hours"), F.sum("tot").alias("total_mm"),
        F.sum("wet").alias("wet_slots"), F.max("mx").alias("max5_mm"),
        F.sum((F.col("tot") >= cfg.phantom_hour_mm).cast("int")).alias("hours_ge_1mm"))
    nb_hourly = hourly.select(F.col("station_id").alias("nb"), "hour", F.col("tot").alias("nb_tot"))
    matched = (hourly.select("station_id", "hour", "qc_day").join(F.broadcast(pairs), "station_id")
               .join(nb_hourly, ["nb", "hour"])
               .groupBy("station_id", "qc_day", "nb", "nb_rank")
               .agg(F.count("*").alias("common_hours"), F.sum("nb_tot").alias("nb_total")))
    rank = Window.partitionBy("station_id", "qc_day").orderBy("nb_rank")
    usable = (matched.join(own.select("station_id", "qc_day", "n_hours"), ["station_id", "qc_day"])
              .filter(F.col("common_hours") >= F.lit(cfg.hour_cover) * F.col("n_hours"))
              .withColumn("k", F.row_number().over(rank)).filter(F.col("k") <= cfg.neighbour_count))
    nb_stats = usable.groupBy("station_id", "qc_day").agg(
        F.count("*").alias("n_neighbours"), F.max("nb_total").alias("nb_max_mm"),
        F.expr("percentile(nb_total, 0.5)").alias("nb_median_mm"),
        F.expr("transform(array_sort(collect_list(struct(k, nb, round(nb_total, 1) AS mm))), x -> concat(x.nb, ':', x.mm))")
        .alias("nb_totals"))
    return (own.join(nb_stats, ["station_id", "qc_day"], "left")
            .fillna({"n_neighbours": 0}))


def stuck_zero_runs(daily: DataFrame, cfg: QCConfig) -> DataFrame:
    """Rule A. One row per run of exact-zero station-days, with the neighbour evidence."""
    order = Window.partitionBy("station_id").orderBy("qc_day").rowsBetween(Window.unboundedPreceding, 0)
    nb_wet = (F.col("n_neighbours") >= cfg.stuck_min_neighbours) & (F.col("nb_median_mm") >= cfg.stuck_wet_median_mm)
    return (daily.withColumn("run", F.sum((F.col("total_mm") > 0).cast("int")).over(order))
            .filter(F.col("total_mm") == 0)
            .groupBy("station_id", "run")
            .agg(F.min("qc_day").alias("start"), F.max("qc_day").alias("end"), F.count("*").alias("days_with_data"),
                 F.sum("n_slots").alias("slots"), F.sum(nb_wet.cast("int")).alias("neighbour_wet_days"),
                 F.sum(F.when(F.col("n_neighbours") >= cfg.stuck_min_neighbours, F.col("nb_median_mm"))).alias("nb_median_sum_mm"),
                 F.max(F.when(F.col("n_neighbours") >= cfg.stuck_min_neighbours, F.col("nb_median_mm"))).alias("nb_median_max_mm"))
            .filter(F.col("neighbour_wet_days") >= cfg.stuck_min_wet_days))


def flagged_days(daily: DataFrame, cfg: QCConfig) -> DataFrame:
    """Rules B and C on station-days."""
    extreme = ((F.col("total_mm") >= cfg.extreme_total_mm) & (F.col("n_neighbours") >= cfg.extreme_min_neighbours)
               & (F.col("nb_max_mm") < F.lit(cfg.extreme_ratio) * F.col("total_mm")))
    phantom = ((F.col("total_mm") >= cfg.phantom_total_mm) & (F.col("hours_ge_1mm") >= cfg.phantom_min_hours)
               & (F.col("n_neighbours") >= cfg.phantom_min_neighbours)
               & (F.col("nb_max_mm") <= F.lit(cfg.phantom_ratio) * F.col("total_mm")))
    return (daily.withColumn("isolated_extreme", extreme).withColumn("phantom_rain", phantom)
            .filter("isolated_extreme OR phantom_rain"))


def repeat_spans(days: list[dict], cfg: QCConfig) -> list[dict]:
    """Rule D on the (small) collected list of B/C days: chains with gaps <= repeat_max_gap_days."""
    by_station: dict[str, list] = {}
    for d in days:
        by_station.setdefault(d["station_id"], []).append(d["qc_day"])
    spans = []
    for sid, ds in sorted(by_station.items()):
        ds = sorted(set(ds))
        chain = [ds[0]]
        for d in ds[1:] + [None]:
            if d is not None and (d - chain[-1]).days <= cfg.repeat_max_gap_days:
                chain.append(d)
                continue
            if len(chain) >= cfg.repeat_min_days:
                spans.append({"station_id": sid, "start": chain[0], "end": chain[-1], "flagged_days": len(chain)})
            if d is not None:
                chain = [d]
    return spans


def spikes(slots: DataFrame, pairs: DataFrame, cfg: QCConfig) -> DataFrame:
    """Rule E. Candidate slots are few, so neighbour support is looked up by exact slot keys."""
    big = (slots.filter(F.col("y") >= cfg.spike_mm).select("station_id", "qc_slot", "y")
           .withColumn("prev_slot", F.col("qc_slot") - SLOT).withColumn("next_slot", F.col("qc_slot") + SLOT))
    prev = slots.select("station_id", F.col("qc_slot").alias("prev_slot"), F.col("y").alias("prev_mm"))
    nxt = slots.select("station_id", F.col("qc_slot").alias("next_slot"), F.col("y").alias("next_mm"))
    adjacent = (big.join(prev, ["station_id", "prev_slot"], "left").join(nxt, ["station_id", "next_slot"], "left")
                .select("station_id", "qc_slot", "y", "prev_mm", "next_mm"))
    lim = F.lit(cfg.spike_adjacent_ratio) * F.col("y")
    cand = adjacent.filter((F.coalesce("prev_mm", F.lit(0.0)) < lim) & (F.coalesce("next_mm", F.lit(0.0)) < lim))
    offsets = F.explode(F.sequence(F.lit(-cfg.spike_window_slots), F.lit(cfg.spike_window_slots))).alias("o")
    near = pairs.filter(F.col("nb_rank") <= cfg.neighbour_count)
    keys = (cand.join(F.broadcast(near), "station_id")
            .select("station_id", "qc_slot", "nb", offsets)
            .withColumn("nb_slot", F.col("qc_slot") + F.col("o") * SLOT))
    nb_vals = slots.select(F.col("station_id").alias("nb"), F.col("qc_slot").alias("nb_slot"), F.col("y").alias("nb_y"))
    support = (keys.join(nb_vals, ["nb", "nb_slot"])
               .groupBy("station_id", "qc_slot")
               .agg(F.countDistinct("nb").alias("n_neighbours"), F.max("nb_y").alias("nb_max_5min_mm")))
    return (cand.join(support, ["station_id", "qc_slot"], "left").fillna({"n_neighbours": 0})
            .filter((F.col("n_neighbours") >= cfg.spike_min_neighbours)
                    & (F.col("nb_max_5min_mm") < cfg.spike_neighbour_mm)))


def config_dict(cfg: QCConfig) -> dict:
    return asdict(cfg)
