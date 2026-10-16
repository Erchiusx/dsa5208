#!/usr/bin/env python3
"""Build rich_features_<year> (see src/rainfall_project/rich_features.py) from cleaned_rainfall_<year>."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from rainfall_project.clean import build_spark  # noqa: E402
from rainfall_project.rich_features import build_year  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int, default=list(range(2017, 2025)))
    parser.add_argument("--interim-dir", type=Path, default=PROJECT_DIR / "data" / "interim")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "data" / "processed")
    args = parser.parse_args()
    spark = build_spark("dsa5208-rich-features")
    try:
        for year in args.years:
            out = args.output_dir / f"rich_features_{year}"
            build_year(spark, args.interim_dir, year).write.mode("overwrite").parquet(str(out))
            n = spark.read.parquet(str(out)).count()
            print(f"{year}: wrote {n:,} station-slot rows to {out}", flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
