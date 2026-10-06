#!/usr/bin/env python3
"""Build the Project 2 threshold-independent 30-minute feature table."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import build_spark  # noqa: E402
from rainfall_project.features import FeaturePaths, build_features  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int, default=list(range(2017, 2025)))
    parser.add_argument("--interim-dir", type=Path, default=PROJECT_DIR / "data" / "interim")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "data" / "processed" / "rainfall_features")
    parser.add_argument("--report", type=Path, default=PROJECT_DIR / "data" / "processed" / "feature_report.json")
    args = parser.parse_args()
    if any(year < 2017 or year > 2024 for year in args.years):
        parser.error("--years must be between 2017 and 2024")
    spark = build_spark("dsa5208-rainfall-features")
    try:
        report = build_features(FeaturePaths(args.interim_dir, args.output_dir, args.report), args.years, spark)
        print(f"Wrote {report['rows_featured']:,} feature rows to {args.output_dir}")
        print(f"Complete training rows: {report['rows_complete_history_and_target']:,}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
