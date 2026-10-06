#!/usr/bin/env python3
"""Run the Project 2 audited Spark cleaning pipeline."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import CleanPaths, build_spark, clean  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int, default=list(range(2017, 2025)))
    parser.add_argument("--raw-dir", type=Path, default=PROJECT_DIR / "data" / "raw")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "data" / "interim" / "cleaned_rainfall")
    parser.add_argument("--report", type=Path, default=PROJECT_DIR / "data" / "interim" / "quality_report.json")
    args = parser.parse_args()
    if any(year < 2017 or year > 2024 for year in args.years):
        parser.error("--years must be between 2017 and 2024")

    spark = build_spark()
    try:
        report = clean(CleanPaths(args.raw_dir, args.output_dir, args.report), args.years, spark)
        print(f"Retained {report['counts']['rows_retained']:,} rows in {args.output_dir}")
        print(f"Wrote quality report to {args.report}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
