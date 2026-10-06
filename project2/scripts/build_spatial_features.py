#!/usr/bin/env python3
"""Create annual multi-station rainfall feature tables using lagged KNN aggregates."""
from __future__ import annotations

import argparse
import json
import sys
from functools import reduce
from pathlib import Path

from pyspark.sql import functions as F

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import build_spark  # noqa: E402
from rainfall_project.spatial import SPATIAL_NUMERIC_FEATURES, add_lagged_neighbor_features, build_neighbor_map  # noqa: E402


def read_years(spark, root: Path, prefix: str, years: list[int]):
    frames = [spark.read.parquet(str(root / f"{prefix}_{year}")) for year in years]
    return reduce(lambda left, right: left.unionByName(right), frames)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int, default=list(range(2017, 2025)))
    parser.add_argument("--neighbor-count", type=int, default=8)
    parser.add_argument("--input-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--input-prefix", default="rainfall_features")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    parser.add_argument("--output-prefix", default="spatial_features")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    args = parser.parse_args()
    if args.neighbor_count < 1:
        parser.error("--neighbor-count must be positive")

    spark = build_spark("dsa5208-spatial-rainfall-features")
    try:
        location_source = read_years(spark, args.input_dir, args.input_prefix, list(range(2017, 2025)))
        locations = [
            row.asDict()
            for row in location_source.groupBy("station_id").agg(
                F.avg("latitude").alias("latitude"), F.avg("longitude").alias("longitude")
            ).collect()
        ]
        neighbors = build_neighbor_map(spark, locations, args.neighbor_count)
        neighbor_rows = [row.asDict() for row in neighbors.orderBy("target_station_id", "neighbor_rank").collect()]
        for year in args.years:
            base = spark.read.parquet(str(args.input_dir / f"{args.input_prefix}_{year}"))
            spatial = add_lagged_neighbor_features(base, neighbors)
            output = args.output_dir / f"{args.output_prefix}_{year}"
            spatial.write.mode("overwrite").partitionBy("year").parquet(str(output))
            report = {
                "year": year,
                "input_rows": base.count(),
                "output_rows": spatial.count(),
                "neighbor_count_requested": args.neighbor_count,
                "spatial_features": SPATIAL_NUMERIC_FEATURES,
                "temporal_rule": "neighbour features use the previous nominal five-minute slot only",
                "nominal_slot_rule": "nearest five-minute slot; reconciles :00 and :59 source offsets",
                "neighbor_map": neighbor_rows,
            }
            report_path = args.report_dir / f"spatial_feature_report_{year}.json"
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps({key: report[key] for key in ("year", "input_rows", "output_rows", "neighbor_count_requested")}, indent=2))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
