"""Nonparametric wet-amount models that share the ZILN occurrence model pi(x).

    P(Y > r | x) = pi(x) * S(r | x),     S(r | x) = P(Y > r | Y > 0, x).

ZILN assumes log Y | Y > 0 is a location-scale family. The models here estimate S on a fixed
grid of edges without any shape assumption, so a comparison with ZILN isolates the choice of
amount model (every candidate uses the same pi and the same assembled features):

  * hazard : continuation-ratio (discrete-time hazard) GBTClassifier. A wet row whose total
             passes edges 1..c contributes one binary row per edge j <= c + 1,
                 label = 1{Y > e_j},  given Y > e_{j-1},
             with the edge index as an extra feature; S(e_j) = prod_{i <= j} h_i(x) is
             monotone in r by construction.
  * rf     : RandomForestClassifier over the wet classes (e_{c-1}, e_c]; averaging leaf class
             frequencies is the quantile-regression-forest estimate of the conditional
             distribution restricted to the grid.
  * mlp    : MultilayerPerceptronClassifier (softmax over the wet classes) on asinh-transformed,
             standardised features, with the station index (feature 0) one-hot encoded.

Wet-only training needs no case weights. Every model returns `S`, an array over GRID with
S[k] = P(Y > GRID[k] | x) (S[0] = pi), so they are scored and ensembled identically.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pyspark.ml.classification import (GBTClassificationModel, GBTClassifier, MultilayerPerceptronClassificationModel,
                                       MultilayerPerceptronClassifier, RandomForestClassificationModel,
                                       RandomForestClassifier)
from pyspark.ml.feature import StandardScaler, StandardScalerModel, VectorAssembler
from pyspark.ml.functions import array_to_vector, vector_to_array
from pyspark.sql import Column, DataFrame, functions as F

EDGES = [0.2, 0.4, 0.5, 1.0, 1.4, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0, 50.0]
J = len(EDGES)
GRID = [0.0, *EDGES]  # S[k] = P(Y > GRID[k] | x)
KINDS = ("hazard", "rf", "mlp")


def wet_class(y: str = "y") -> Column:
    """Number of edges strictly below y: wet class c in 0..J, i.e. y in (e_c, e_{c+1}]."""
    return sum((F.col(y) > F.lit(e)).cast("int") for e in EDGES)


def hazard_rows(wet: DataFrame) -> DataFrame:
    """One binary row per edge a wet row reaches: bin j in 1..min(c + 1, J), label 1{c >= j}."""
    return (wet.withColumn("c", wet_class())
            .withColumn("bin", F.explode(F.sequence(F.lit(1), F.least(F.col("c") + 1, F.lit(J)))))
            .withColumn("label", (F.col("c") >= F.col("bin")).cast("double"))
            .withColumn("bin", F.col("bin").cast("double")))


def _with_pi(s_pos: Column) -> Column:
    """[pi, pi * S(e_1), ..., pi * S(e_J)]."""
    return F.concat(F.array(F.col("pi")), F.transform(s_pos, lambda v: v * F.col("pi")))


def _upper_sums(probs: Column) -> Column:
    """Class probabilities p_0..p_J -> [sum_{c >= j} p_c for j = 1..J]."""
    return F.transform(F.sequence(F.lit(1), F.lit(J)),
                       lambda j: F.aggregate(F.slice(probs, j + 1, F.lit(J + 1) - j), F.lit(0.0), lambda a, b: a + b))


def _mlp_inputs(frame: DataFrame, n_station: int) -> DataFrame:
    """asinh of the numeric features plus a one-hot station index (an unseen station is all zeros)."""
    arr = vector_to_array("features")
    numeric = F.transform(F.slice(arr, 2, F.size(arr) - 1), lambda v: F.asinh(v))
    onehot = F.transform(F.sequence(F.lit(0), F.lit(n_station - 1)), lambda k: (k == arr[0].cast("int")).cast("double"))
    return frame.withColumn("xf", array_to_vector(F.concat(numeric, onehot)))


@dataclass
class AmountModel:
    kind: str
    model: object
    scaler: StandardScalerModel | None = None
    meta: dict | None = None

    def survival(self, base: DataFrame, key: list[str]) -> DataFrame:
        """`base` has key columns, y, pi and the assembled `features`; returns key, y, S."""
        if self.kind == "hazard":
            ex = (base.select(*key, "features", F.explode(F.sequence(F.lit(1), F.lit(J))).alias("bin"))
                  .withColumn("bin", F.col("bin").cast("double")))
            ex = VectorAssembler(inputCols=["features", "bin"], outputCol="hfeatures").transform(ex)
            h = (self.model.transform(ex).select(*key, "bin", vector_to_array("h_probability")[1].alias("h"))
                 .groupBy(*key).agg(F.sort_array(F.collect_list(F.struct("bin", "h"))).alias("hs")))
            hs = F.transform("hs", lambda s: s["h"])
            s_pos = F.transform(hs, lambda v, i: F.aggregate(F.slice(hs, 1, i + 1), F.lit(1.0), lambda a, b: a * b))
            h = h.select(*key, s_pos.alias("s_pos"))
            return base.select(*key, "y", "pi").join(h, key).select(*key, "y", _with_pi(F.col("s_pos")).alias("S"))
        x = base
        if self.kind == "mlp":
            x = self.scaler.transform(_mlp_inputs(x, self.meta["n_station"]))
        probs = vector_to_array(f"{self.kind}_probability")
        return self.model.transform(x).select(*key, "y", _with_pi(_upper_sums(probs)).alias("S"))

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self.model.write().overwrite().save(str(path / self.kind))
        if self.scaler is not None:
            self.scaler.write().overwrite().save(str(path / "scaler"))
        (path / "amount_meta.json").write_text(json.dumps({**(self.meta or {}), "kind": self.kind, "edges": EDGES}, indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> "AmountModel":
        meta = json.loads((path / "amount_meta.json").read_text())
        kind = meta["kind"]
        loader = {"hazard": GBTClassificationModel, "rf": RandomForestClassificationModel,
                  "mlp": MultilayerPerceptronClassificationModel}[kind]
        scaler = StandardScalerModel.load(str(path / "scaler")) if (path / "scaler").exists() else None
        return cls(kind, loader.load(str(path / kind)), scaler, meta)


def fit_amount_model(kind: str, wet: DataFrame, work_dir: Path, params: dict, seed: int = 5208, log=print) -> AmountModel:
    """`wet` has `features` (ZILN-assembled) and y > 0 for 2017-2022 training rows."""
    spark = wet.sparkSession
    if kind == "hazard":
        rows_dir = work_dir / "hazard_rows"
        if not rows_dir.exists():
            rows = VectorAssembler(inputCols=["features", "bin"], outputCol="hfeatures").transform(hazard_rows(wet))
            rows.select("hfeatures", "label", "bin").write.parquet(str(rows_dir))
        rows = spark.read.parquet(str(rows_dir))
        log(f"hazard rows: {rows.count():,}")
        gbt = {**dict(maxIter=100, maxDepth=6, stepSize=0.2, maxBins=128, subsamplingRate=0.8), **params}
        model = (GBTClassifier(featuresCol="hfeatures", labelCol="label", seed=seed, **gbt)
                 .setProbabilityCol("h_probability").setRawPredictionCol("h_raw").setPredictionCol("h_prediction")
                 .fit(rows))
        return AmountModel(kind, model, None, {"params": gbt, "n_rows": rows.count()})
    data = wet.withColumn("c", wet_class().cast("double"))
    if kind == "rf":
        # cacheNodeIds would grow the node-id RDD lineage by one step per pass (no checkpoint dir),
        # which overflows the stack in task serialization after ~1000 passes
        rf = {**dict(numTrees=60, maxDepth=12, minInstancesPerNode=200, featureSubsetStrategy="onethird",
                     subsamplingRate=0.5, maxBins=128, maxMemoryInMB=384, cacheNodeIds=False), **params}
        model = (RandomForestClassifier(featuresCol="features", labelCol="c", seed=seed, **rf)
                 .setProbabilityCol("rf_probability").setRawPredictionCol("rf_raw").setPredictionCol("rf_prediction")
                 .fit(data))
        return AmountModel(kind, model, None, {"params": rf})
    if kind == "mlp":
        n_station = int(data.select(F.max(vector_to_array("features")[0])).first()[0]) + 1
        data = _mlp_inputs(data, n_station)
        scaler = StandardScaler(inputCol="xf", outputCol="xs", withMean=True, withStd=True).fit(data)
        data = scaler.transform(data).select("xs", "c").cache()
        n_in = len(data.first()["xs"])
        mlp = {**dict(layers=[n_in, 64, 64, J + 1], maxIter=300, blockSize=1024, solver="l-bfgs"), **params}
        model = (MultilayerPerceptronClassifier(featuresCol="xs", labelCol="c", seed=seed, **mlp)
                 .setProbabilityCol("mlp_probability").setRawPredictionCol("mlp_raw").setPredictionCol("mlp_prediction")
                 .fit(data))
        data.unpersist()
        return AmountModel(kind, model, scaler, {"params": mlp, "n_station": n_station})
    raise ValueError(kind)


def survival_at(S: np.ndarray, r: float) -> np.ndarray:
    """P(Y > r) for any r >= 0 from grid survival arrays (n, J + 1): linear on [0, e_1],
    log-log interpolation between edges, Pareto extrapolation beyond the last edge."""
    S = np.atleast_2d(np.asarray(S, dtype=np.float64))
    g = np.asarray(GRID)
    if r <= 0:
        return S[:, 0]
    if r <= g[1]:
        return S[:, 0] + (S[:, 1] - S[:, 0]) * r / g[1]
    ls = np.log(np.maximum(S, 1e-300))
    k = min(int(np.searchsorted(g, r, side="left")), len(g) - 1)
    lo = k - 1
    t = (np.log(r) - np.log(g[lo])) / (np.log(g[k]) - np.log(g[lo]))
    return np.exp(ls[:, lo] + t * (ls[:, k] - ls[:, lo]))


def _trapezoid_weights() -> list[float]:
    g = GRID
    return [(g[1] - g[0]) / 2, *[(g[k + 1] - g[k - 1]) / 2 for k in range(1, J)], (g[J] - g[J - 1]) / 2]


def score_columns(S: str = "S", y: str = "y") -> dict[str, Column]:
    """Proper scores of a grid forecast: log score of the class of y (zero, the J wet classes
    and the open top class), ranked probability score over GRID, and the trapezoid-rule
    approximation of CRPS on [0, 50] mm (sum of grid Brier scores times grid spacing)."""
    grid = F.array(*[F.lit(g) for g in GRID])
    weights = F.array(*[F.lit(w) for w in _trapezoid_weights()])
    yv, s = F.col(y), F.col(S)
    c = F.when(yv <= 0, F.lit(0)).otherwise(wet_class(y) + 1)
    p_c = (F.when(c == 0, 1 - F.element_at(s, 1))
           .when(c == J + 1, F.element_at(s, J + 1))
           .otherwise(F.element_at(s, c) - F.element_at(s, c + 1)))
    sq = F.transform(s, lambda v, i: (v - (yv > F.element_at(grid, i + 1)).cast("double")) ** 2)
    total = lambda arr: F.aggregate(arr, F.lit(0.0), lambda a, b: a + b)  # noqa: E731
    return {"log_score": -F.log(F.greatest(p_c, F.lit(1e-12))), "rps": total(sq),
            "crps_grid": total(F.zip_with(sq, weights, lambda a, b: a * b))}


def ziln_survival(ziln, frame: DataFrame, key: list[str]) -> DataFrame:
    """ZILN P(Y > GRID[k]) on the same grid, from the selected sigma / error distribution."""
    z = ziln.transform(frame)
    return z.select(*key, "y", F.array(F.col("pi"), *[ziln.exceedance(e) for e in EDGES]).alias("S"))
