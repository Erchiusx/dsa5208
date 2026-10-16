"""Load annual model inputs for a named feature set."""
from __future__ import annotations

from functools import reduce
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession

from rainfall_project.rich_features import RICH_FEATURES, with_rich_features
from rainfall_project.ziln import FEATURES

FEATURE_SETS = {"spatial": FEATURES, "rich": [*FEATURES, *RICH_FEATURES]}


def load_years(spark: SparkSession, processed_dir: Path, years: list[int], feature_set: str = "spatial") -> DataFrame:
    frames = []
    for year in years:
        frame = spark.read.parquet(str(processed_dir / f"spatial_features_{year}"))
        if feature_set == "rich":
            frame = with_rich_features(frame, spark.read.parquet(str(processed_dir / f"rich_features_{year}")))
        frames.append(frame)
    return reduce(lambda left, right: left.unionByName(right), frames)
