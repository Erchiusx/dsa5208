#!/usr/bin/env python3
"""Rule-based QC of the cleaned five-minute readings (see src/rainfall_project/qc.py).

Reads data/interim/cleaned_rainfall_<Y> for all years (the rules look across year
boundaries), writes the masked copy to <output-dir>/cleaned_rainfall_<Y> with the same
schema and partitioning (flagged readings are removed, so downstream eligibility treats
them as missing), plus an audit trail: every flag as CSV, the per-station-day QC table
and a JSON summary with rows per year before and after.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import shutil
import sys
import time
from pathlib import Path

from pyspark.sql import functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import build_spark  # noqa: E402
from rainfall_project.qc import (QCConfig, config_dict, daily_table, flagged_days, neighbour_pairs,  # noqa: E402
                                 read_cleaned, repeat_spans, spikes, station_slots, stuck_zero_runs,
                                 with_slot_and_day)

FLAG_COLUMNS = ["rule", "station_id", "start", "end", "days_with_data", "own_total_mm", "own_max5_mm", "hours_ge_1mm",
                "n_neighbours", "nb_max_mm", "nb_median_mm", "neighbour_wet_days", "nb_median_sum_mm",
                "nb_median_max_mm", "nb_totals", "detail"]


def r(x, nd=2):
    return None if x is None else round(float(x), nd)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int, default=list(range(2017, 2025)))
    parser.add_argument("--interim-dir", type=Path, default=PROJECT_DIR / "data" / "interim")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "data" / "interim_qc")
    parser.add_argument("--flags-csv", type=Path, default=PROJECT_DIR / "reports" / "qc_flags.csv")
    parser.add_argument("--summary", type=Path, default=PROJECT_DIR / "reports" / "qc_summary.json")
    parser.add_argument("--start", help="optional ISO date: restrict QC to readings on/after it (smoke tests)")
    parser.add_argument("--end", help="optional ISO date: restrict QC to readings before it (smoke tests)")
    parser.add_argument("--no-write", action="store_true", help="compute flags only, do not write the masked data")
    args = parser.parse_args()
    cfg = QCConfig()
    if not args.no_write and args.output_dir.resolve() == args.interim_dir.resolve():
        parser.error("--output-dir must differ from --interim-dir; the original cleaned data is never overwritten")

    spark = build_spark("dsa5208-rainfall-qc")
    t0 = time.time()
    log = lambda msg: print(f"[{time.time() - t0:6.0f}s] {msg}", flush=True)  # noqa: E731
    work = args.output_dir / "_qc_work"
    try:
        cleaned = read_cleaned(spark, args.interim_dir, args.years)
        if args.start:
            cleaned = cleaned.filter(F.col("observation_ts") >= F.to_timestamp(F.lit(args.start)))
        if args.end:
            cleaned = cleaned.filter(F.col("observation_ts") < F.to_timestamp(F.lit(args.end)))
        pairs, pair_rows = neighbour_pairs(spark, cleaned, cfg.radius_km)
        station_slots(cleaned).write.mode("overwrite").parquet(str(work / "slots"))
        slots = spark.read.parquet(str(work / "slots"))
        log("wrote station-slot table")
        daily_table(slots, pairs, cfg).write.mode("overwrite").parquet(str(args.output_dir / "qc_station_days"))
        daily = spark.read.parquet(str(args.output_dir / "qc_station_days")).cache()
        log(f"station-day table: {daily.count():,} rows")

        runs = [row.asDict() for row in stuck_zero_runs(daily, cfg).orderBy("station_id", "start").collect()]
        bc = [row.asDict() for row in flagged_days(daily, cfg).orderBy("station_id", "qc_day").collect()]
        spans = repeat_spans(bc, cfg)
        spk = [row.asDict() for row in spikes(slots, pairs, cfg).orderBy("station_id", "qc_slot").collect()]
        log(f"flags: stuck_zero runs={len(runs)}, isolated_extreme days={sum(d['isolated_extreme'] for d in bc)}, "
            f"phantom_rain days={sum(d['phantom_rain'] for d in bc)}, repeat spans={len(spans)}, spikes={len(spk)}")

        # ---- flag table (one row per flagged event) -------------------------------------------------
        flags = []
        for x in runs:
            flags.append({"rule": "A_stuck_zero", "station_id": x["station_id"], "start": x["start"], "end": x["end"],
                          "days_with_data": x["days_with_data"], "own_total_mm": 0.0,
                          "neighbour_wet_days": x["neighbour_wet_days"], "nb_median_sum_mm": r(x["nb_median_sum_mm"], 1),
                          "nb_median_max_mm": r(x["nb_median_max_mm"], 1), "detail": f"{x['slots']} zero readings"})
        for x in bc:
            rule = "B_isolated_extreme" if x["isolated_extreme"] else "C_phantom_rain"
            if x["isolated_extreme"] and x["phantom_rain"]:
                rule = "B_isolated_extreme+C_phantom_rain"
            flags.append({"rule": rule, "station_id": x["station_id"], "start": x["qc_day"], "end": x["qc_day"],
                          "days_with_data": 1, "own_total_mm": r(x["total_mm"], 1), "own_max5_mm": r(x["max5_mm"], 2),
                          "hours_ge_1mm": x["hours_ge_1mm"], "n_neighbours": x["n_neighbours"],
                          "nb_max_mm": r(x["nb_max_mm"], 1), "nb_median_mm": r(x["nb_median_mm"], 1),
                          "nb_totals": " ".join(x["nb_totals"] or []), "detail": f"{x['n_slots']} readings"})
        for x in spans:
            flags.append({"rule": "D_repeat", "station_id": x["station_id"], "start": x["start"], "end": x["end"],
                          "detail": f"{x['flagged_days']} B/C days <= {cfg.repeat_max_gap_days} d apart"})
        for x in spk:
            ts = dt.datetime.fromtimestamp(x["qc_slot"], dt.timezone(dt.timedelta(hours=8)))
            day = (ts - dt.timedelta(minutes=5)).date()
            flags.append({"rule": "E_spike", "station_id": x["station_id"], "start": day, "end": day,
                          "own_max5_mm": r(x["y"], 2), "n_neighbours": x["n_neighbours"],
                          "nb_max_mm": r(x["nb_max_5min_mm"], 2),
                          "detail": f"{ts:%Y-%m-%d %H:%M} SGT, prev={x['prev_mm']} next={x['next_mm']} mm; "
                                    f"nb_max_mm = max neighbour 5-min value within +-30 min"})
        flags.sort(key=lambda f: (str(f["start"]), f["station_id"], f["rule"]))
        args.flags_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.flags_csv.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FLAG_COLUMNS)
            w.writeheader()
            for f in flags:
                w.writerow({k: f.get(k) for k in FLAG_COLUMNS})
        log(f"wrote {len(flags)} flags to {args.flags_csv}")

        # ---- masks -----------------------------------------------------------------------------------
        one = dt.timedelta(days=cfg.day_buffer)
        day_masks = [(x["station_id"], x["start"], x["end"], "A_stuck_zero") for x in runs]
        day_masks += [(x["station_id"], x["qc_day"] - one, x["qc_day"] + one,
                       "B_isolated_extreme" if x["isolated_extreme"] else "C_phantom_rain") for x in bc]
        day_masks += [(x["station_id"], x["start"] - one, x["end"] + one, "D_repeat") for x in spans]
        dm = spark.createDataFrame(day_masks or [("", dt.date(1970, 1, 1), dt.date(1970, 1, 1), "none")],
                                   "station_id string, mask_start date, mask_end date, rule string")
        sm = spark.createDataFrame([(x["station_id"], int(x["qc_slot"]), "E_spike") for x in spk] or [("", 0, "none")],
                                   "station_id string, qc_slot long, rule string")
        in_span = (F.col("qc_day") >= F.col("mask_start")) & (F.col("qc_day") <= F.col("mask_end"))

        # masked station-days per year and rule (days with data only)
        days_by_rule = (daily.join(F.broadcast(dm), "station_id").filter(in_span)
                        .groupBy(F.year("qc_day").alias("year"), "rule").agg(F.countDistinct("station_id", "qc_day").alias("n"))
                        .collect())
        masked_days_total = (daily.join(F.broadcast(dm), "station_id").filter(in_span)
                             .groupBy(F.year("qc_day").alias("year")).agg(F.countDistinct("station_id", "qc_day").alias("n"))
                             .collect())

        rows = {}
        for year in args.years:
            src = spark.read.parquet(str(args.interim_dir / f"cleaned_rainfall_{year}"))
            if args.start:
                src = src.filter(F.col("observation_ts") >= F.to_timestamp(F.lit(args.start)))
            if args.end:
                src = src.filter(F.col("observation_ts") < F.to_timestamp(F.lit(args.end)))
            tagged = with_slot_and_day(src)
            by_day = tagged.join(F.broadcast(dm), (tagged.station_id == dm.station_id) & in_span, "left_semi")
            by_slot = tagged.join(F.broadcast(sm.select("station_id", "qc_slot")), ["station_id", "qc_slot"], "left_semi")
            kept = (tagged.join(F.broadcast(dm), (tagged.station_id == dm.station_id) & in_span, "left_anti")
                    .join(F.broadcast(sm.select("station_id", "qc_slot")), ["station_id", "qc_slot"], "left_anti")
                    .drop("qc_slot", "qc_day"))
            per_rule = {}
            for rule in sorted({m[3] for m in day_masks}):
                rm = F.broadcast(dm.filter(F.col("rule") == rule))
                per_rule[rule] = tagged.join(rm, (tagged.station_id == rm.station_id) & in_span, "left_semi").count()
            per_rule["E_spike"] = by_slot.count()
            n_before = src.count()
            n_after = None
            if not args.no_write:
                out = args.output_dir / f"cleaned_rainfall_{year}"
                kept.select(*src.columns).write.mode("overwrite").partitionBy("year").parquet(str(out))
                n_after = spark.read.parquet(str(out)).count()
            else:
                n_after = kept.count()
            rows[year] = {"rows_before": n_before, "rows_after": n_after, "rows_removed": n_before - n_after,
                          "rows_removed_day_masks": by_day.count(),
                          "rows_matched_by_rule": per_rule}  # a reading can match several rules
            log(f"{year}: {n_before:,} -> {n_after:,} readings ({n_before - n_after:,} removed)")

        def per_year(items, key):
            out = {}
            for f in items:
                out.setdefault(str(key(f)), {}).setdefault(f["rule"], 0)
                out[str(key(f))][f["rule"]] += 1
            return out

        summary = {
            "config": config_dict(cfg),
            "rules": {
                "A_stuck_zero": "run of consecutive station-days with data and exact-zero total (no-data days do not break it) "
                                f"containing >= {cfg.stuck_min_wet_days} days whose hour-matched neighbour median >= "
                                f"{cfg.stuck_wet_median_mm} mm (>= {cfg.stuck_min_neighbours} neighbours); whole run masked",
                "B_isolated_extreme": f"station-day total >= {cfg.extreme_total_mm} mm and wettest hour-matched neighbour "
                                      f"< {cfg.extreme_ratio:.0%} of it (>= {cfg.extreme_min_neighbours} neighbours); day +-{cfg.day_buffer} masked",
                "C_phantom_rain": f"station-day total >= {cfg.phantom_total_mm} mm with >= {cfg.phantom_hour_mm} mm in >= "
                                  f"{cfg.phantom_min_hours} different hours, wettest of >= {cfg.phantom_min_neighbours} hour-matched "
                                  f"neighbours <= {cfg.phantom_ratio:.0%} of it; day +-{cfg.day_buffer} masked",
                "D_repeat": f">= {cfg.repeat_min_days} B/C days at a station with consecutive flags <= {cfg.repeat_max_gap_days} "
                            f"days apart; span first..last +-{cfg.day_buffer} day masked",
                "E_spike": f"single 5-min value >= {cfg.spike_mm} mm, own previous and next readings < "
                           f"{cfg.spike_adjacent_ratio:.0%} of it, and no reading >= {cfg.spike_neighbour_mm} mm at any of the "
                           f"{cfg.neighbour_count} nearest neighbours within {cfg.radius_km} km (>= {cfg.spike_min_neighbours} "
                           f"reporting) within +-{cfg.spike_window_slots * 5} min; that slot masked",
                "neighbours": f"stations within {cfg.radius_km} km; daily totals are hour-matched (only hours in which the "
                              f"station reported), a neighbour must cover >= {cfg.hour_cover:.0%} of those hours, nearest "
                              f"{cfg.neighbour_count} used",
            },
            "flag_events_by_start_year": per_year(flags, lambda f: f["start"].year),
            "masked_station_days_by_year_and_rule": {str(y): {row["rule"]: row["n"] for row in days_by_rule if row["year"] == y}
                                                     for y in sorted({row["year"] for row in days_by_rule})},
            "masked_station_days_by_year": {str(row["year"]): row["n"] for row in sorted(masked_days_total, key=lambda x: x["year"])},
            "readings_by_year": {str(y): v for y, v in rows.items()},
            "flags_csv": str(args.flags_csv.relative_to(PROJECT_DIR)) if args.flags_csv.is_relative_to(PROJECT_DIR) else str(args.flags_csv),
            "neighbour_pairs_within_radius": len(pair_rows),
        }
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, indent=2, default=str) + "\n")
        log(f"wrote {args.summary}")
        shutil.rmtree(work, ignore_errors=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
