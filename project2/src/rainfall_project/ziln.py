"""Zero-inflated lognormal (ZILN) model for 30-minute rainfall, built from Spark ML estimators.

    P(Y = 0 | x) = 1 - pi(x),     log Y | Y > 0, x  ~  Normal(m(x), s(x)^2)

so for any threshold r > 0,  P(Y > r | x) = pi(x) * Phi((m(x) - log r) / s(x)).

The ZILN log-likelihood separates into a Bernoulli term in pi and a Gaussian term in
(m, s) on wet rows, so each part is fitted by its own maximum-likelihood problem:
  * pi : GBTClassifier on 1{Y > 0} with log loss. Dry rows are subsampled at rate q and
         weighted 1/q, which keeps the weighted log loss unbiased and pi calibrated.
  * m  : GBTRegressor (squared loss) on log Y over wet rows.
  * s  : given m, the MLE of s(x)^2 is E[(log Y - m(x))^2 | x]; estimated from
         cross-fitted residuals either as a constant or with a GBTRegressor.
One fitted model therefore serves every threshold, and P(Y > r) is monotone in r.

Error distribution. ZILN is the location-scale model log Y = m(x) + s(x) * eps with
eps ~ N(0, 1). Wet 30-minute totals pile up at one tip (0.2 mm), which makes log Y
right-skewed, so a Gaussian eps gives too thin an upper tail. `error_dist="empirical"`
keeps m and s but replaces N(0, 1) by the distribution G of cross-fitted standardised
residuals (a quantile table, with exponential tails beyond it, i.e. Pareto tails in y):
P(Y > r) = pi(x) * (1 - G((log r - m(x)) / s(x))).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from pyspark.ml import PipelineModel
from pyspark.ml.classification import GBTClassificationModel, GBTClassifier
from pyspark.ml.feature import StringIndexer, VectorAssembler
from pyspark.ml.functions import vector_to_array
from pyspark.ml.regression import GBTRegressionModel, GBTRegressor
from pyspark.sql import DataFrame, functions as F
from pyspark.sql.functions import pandas_udf
from pyspark.sql.types import DoubleType, StructField, StructType

from rainfall_project.spatial import SPATIAL_NUMERIC_FEATURES

BASE_FEATURES = [
    "station_index", "longitude", "latitude", "rainfall_last_5m_mm",
    "rainfall_last_15m_mm", "rainfall_last_30m_mm", "rainfall_last_60m_mm",
    "hour_sin", "hour_cos", "month_sin", "month_cos", "day_of_week_sgt",
]
FEATURES = [*BASE_FEATURES, *SPATIAL_NUMERIC_FEATURES]
TARGET = "future_30m_rainfall_mm"
SIGMA_FLOOR = 0.05
DELTA = 0.2  # tipping-bucket resolution (mm)


def ship_package(spark) -> None:
    """Make `rainfall_project` importable in Python workers (UDF closures reference it)."""
    import shutil
    import tempfile
    pkg = Path(__file__).resolve().parent
    archive = shutil.make_archive(str(Path(tempfile.mkdtemp()) / "rainfall_project"), "zip",
                                  root_dir=pkg.parent, base_dir=pkg.name)
    spark.sparkContext.addPyFile(archive)


def eligible(frame: DataFrame) -> DataFrame:
    # Readings are multiples of 0.001 mm, but summing doubles leaves errors (5 x 0.4 = 2.0000000000000004)
    # and 2024 readings >= 8 mm carry float32 noise (8.60001); both would count an exact r as "> r".
    return (frame.filter("history_60m_complete AND future_30m_complete")
            .withColumn("y", F.round(F.col(TARGET), 3)))


QUANTILE_PROBS = [1e-5, 2e-5, 5e-5, 1e-4, 2e-4, 5e-4, *[i / 1000 for i in range(1, 1000)],
                  0.9995, 0.9998, 0.9999, 0.99995, 0.99998, 0.99999]
BIN_QUANTILE_PROBS = [1e-4, 2e-4, 5e-4, *[i / 1000 for i in range(1, 1000)], 0.9995, 0.9998, 0.9999]
M_BINS = 10
_U_GRID = (np.arange(2000) + 0.5) / 2000  # midpoints for integrals over the wet-amount quantile function


class ErrorDist:
    """CDF / survival / quantile function of the standardised log-residual eps."""

    def __init__(self, table: dict | None):
        self.gaussian = table is None
        if not self.gaussian:
            p = np.asarray(table["p"], dtype=np.float64)
            q = np.asarray(table["q"], dtype=np.float64)
            q = np.maximum.accumulate(q) + np.arange(q.size) * 1e-12  # strictly increasing knots
            from scipy.special import ndtri
            # interpolate linearly in probit space: exact for Gaussian eps, smooth near it
            self.p, self.q, self.w = p, q, ndtri(p)
            # exponential tails fitted between the 1e-5 / 1e-3 (lower) and 0.999 / 0.99999 (upper) knots
            i3, j3 = int(np.searchsorted(p, 1e-3)), int(np.searchsorted(p, 0.999))
            self.lam_lo = math.log(p[i3] / p[0]) / max(q[i3] - q[0], 1e-9)
            self.lam_hi = math.log((1 - p[j3]) / (1 - p[-1])) / max(q[-1] - q[j3], 1e-9)

    def cdf(self, z):
        from scipy.special import ndtr
        if self.gaussian:
            return ndtr(z)
        p, q = self.p, self.q
        with np.errstate(over="ignore"):
            mid = ndtr(np.interp(z, q, self.w))
            lo = p[0] * np.exp(np.minimum(self.lam_lo * (z - q[0]), 0.0))
            hi = 1 - (1 - p[-1]) * np.exp(-self.lam_hi * np.maximum(z - q[-1], 0.0))
        return np.where(z < q[0], lo, np.where(z > q[-1], hi, mid))

    def sf(self, z):
        from scipy.special import ndtr
        if self.gaussian:
            return ndtr(-z)
        p, q = self.p, self.q
        with np.errstate(over="ignore"):
            mid = ndtr(-np.interp(z, q, self.w))
            hi = (1 - p[-1]) * np.exp(-self.lam_hi * np.maximum(z - q[-1], 0.0))
            lo = 1 - p[0] * np.exp(np.minimum(self.lam_lo * (z - q[0]), 0.0))
        return np.where(z > q[-1], hi, np.where(z < q[0], lo, mid))

    def ppf(self, u):
        from scipy.special import ndtri
        if self.gaussian:
            return ndtri(u)
        p, q = self.p, self.q
        mid = np.interp(ndtri(np.clip(u, 1e-300, 1 - 1e-16)), self.w, q)
        with np.errstate(divide="ignore"):
            lo = q[0] + np.log(np.maximum(u, 1e-300) / p[0]) / self.lam_lo
            hi = q[-1] - np.log(np.maximum(1 - u, 1e-300) / (1 - p[-1])) / self.lam_hi
        return np.where(u < p[0], lo, np.where(u > p[-1], hi, mid))


def _error_bins(table: dict | None):
    """(edges, [ErrorDist per bin]); a single bin unless the table is stratified by m."""
    if table is not None and "edges" in table:
        return np.asarray(table["edges"], dtype=np.float64), [ErrorDist(t) for t in table["tables"]]
    return np.empty(0), [ErrorDist(table)]


def _per_bin(edges, dists, m, fn, *arrays):
    """Apply fn(*arrays[idx], G_b) on the rows whose location m falls in bin b."""
    if len(dists) == 1:
        return fn(*arrays, dists[0])
    bins = np.searchsorted(edges, m)
    out = None
    for b, G in enumerate(dists):
        idx = np.nonzero(bins == b)[0]
        if idx.size == 0:
            continue
        part = fn(*(a[idx] for a in arrays), G)
        if out is None:
            out = {k: np.full(m.shape, np.nan) for k in part} if isinstance(part, dict) else np.full(m.shape, np.nan)
        if isinstance(part, dict):
            for k, v in part.items():
                out[k][idx] = v
        else:
            out[idx] = part
    return out


def _exceed_np(pi, m, s, r, G):
    with np.errstate(divide="ignore"):
        z = (np.log(np.where(r > 0, r, 1.0)) - m) / s
    return np.where(r > 0, pi * G.sf(z), pi)


def make_exceedance_udf(table: dict | None):
    edges, dists = _error_bins(table)

    @pandas_udf(DoubleType())
    def exceed(pi: pd.Series, m: pd.Series, s: pd.Series, r: pd.Series) -> pd.Series:
        a = [v.to_numpy(dtype=np.float64) for v in (pi, m, s, r)]
        return pd.Series(_per_bin(edges, dists, a[1], _exceed_np, *a))
    return exceed


def score_rows(pi, m, s, y, G: ErrorDist):
    """numpy: CRPS, density NLL (Gaussian only), lattice NLL and PIT bin edges."""
    pi = np.clip(pi, 1e-12, 1 - 1e-12)
    pos = y > 0
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        ly = np.log(np.where(pos, y, 1.0))
        if G.gaussian:
            from scipy.special import ndtr
            ez = np.exp(m + 0.5 * s * s)
            cdf_y = np.where(pos, ndtr((ly - m) / s), 0.0)
            partial = np.where(pos, ez * ndtr((ly - m - s * s) / s), 0.0)
            eabs = ez - y + 2 * (y * cdf_y - partial)
            gini = 2 * ez * (2 * ndtr(s / math.sqrt(2)) - 1)
            z = (ly - m) / s
            dens = np.where(pos, -np.log(pi) + ly + np.log(s) + 0.5 * math.log(2 * math.pi) + 0.5 * z * z, -np.log1p(-pi))
        else:
            eps = G.ppf(_U_GRID)                                     # shared quantiles of eps
            Q = np.exp(m[:, None] + s[:, None] * eps[None, :])       # wet-amount quantile function per row
            ez = Q.mean(1)
            eabs = np.abs(Q - y[:, None]).mean(1)
            gini = 2 * (Q * (2 * _U_GRID - 1)[None, :]).mean(1)
            dens = np.full_like(y, np.nan)
        crps = (1 - pi) * y + pi * eabs - pi * (1 - pi) * ez - 0.5 * pi * pi * gini
        k = np.round(y / DELTA)
        lo = np.where(k == 0, 0.0, (k - 0.5) * DELTA)
        hi = (k + 0.5) * DELTA
        a = (np.log(np.where(lo > 0, lo, 1.0)) - m) / s
        b = (np.log(hi) - m) / s
        G_lo = np.where(lo > 0, G.cdf(a), 0.0); G_hi = G.cdf(b)
        upper = np.where(lo > 0, G.sf(a), 1.0) - G.sf(b)
        mass = np.where(G_hi < 0.5, G_hi - G_lo, upper)
        lat = np.where(k == 0, (1 - pi) + pi * G_hi, pi * mass)
        F_hi = (1 - pi) + pi * G_hi
        F_lo = np.where(k == 0, 0.0, (1 - pi) + pi * G_lo)
    return {"crps": crps, "nll_density": dens, "nll_lattice": -np.log(np.maximum(lat, 1e-300)), "pit_lo": F_lo, "pit_hi": F_hi}


def make_scores_udf(table: dict | None):
    edges, dists = _error_bins(table)

    @pandas_udf(StructType([StructField(n, DoubleType()) for n in ("crps", "nll_density", "nll_lattice", "pit_lo", "pit_hi")]))
    def scores(pi: pd.Series, m: pd.Series, s: pd.Series, y: pd.Series) -> pd.DataFrame:
        a = [v.to_numpy(dtype=np.float64) for v in (pi, m, s, y)]
        return pd.DataFrame(_per_bin(edges, dists, a[1], score_rows, *a))
    return scores


_GAUSSIAN_EXCEED = make_exceedance_udf(None)
_GAUSSIAN_SCORES = make_scores_udf(None)


def exceedance_probability(pi, m, s, threshold_mm, udf=None) -> F.Column:
    """P(Y > r) as a Column; `threshold_mm` may be a number or a Column."""
    r = threshold_mm if isinstance(threshold_mm, F.Column) else F.lit(float(threshold_mm))
    return (udf or _GAUSSIAN_EXCEED)(pi, m, s, r.cast("double"))


def distribution_scores(pi, m, s, y, udf=None) -> F.Column:
    return (udf or _GAUSSIAN_SCORES)(pi, m, s, y)


@dataclass
class ZILNModel:
    prep: PipelineModel
    occurrence: GBTClassificationModel
    location: GBTRegressionModel
    scale: GBTRegressionModel | None
    sigma_const: float
    sigma_mode: str = "gbt"  # "gbt" or "const"
    meta: dict | None = None
    error_dist: str = "gaussian"  # "gaussian" (ZILN) or "empirical"
    quantiles: dict | None = None  # per sigma mode: {"p": [...], "q": [...]} of cross-fitted standardised residuals

    def error_table(self, sigma_mode: str | None = None, error_dist: str | None = None):
        dist, mode = error_dist or self.error_dist, sigma_mode or self.sigma_mode
        if dist == "gaussian":
            return None
        return self.quantiles[f"{mode}_by_m" if dist == "empirical_by_m" else mode]

    def exceedance(self, threshold_mm, sigma_mode=None, error_dist=None) -> F.Column:
        udf = make_exceedance_udf(self.error_table(sigma_mode, error_dist))
        return exceedance_probability("pi", "m", "s", threshold_mm, udf)

    def scores(self, y="y", sigma_mode=None, error_dist=None) -> F.Column:
        return distribution_scores("pi", "m", "s", y, make_scores_udf(self.error_table(sigma_mode, error_dist)))

    def transform(self, frame: DataFrame, sigma_mode: str | None = None) -> DataFrame:
        mode = sigma_mode or self.sigma_mode
        x = self.prep.transform(frame)
        x = self.occurrence.transform(x).withColumn("pi", vector_to_array("occ_probability")[1])
        x = self.location.transform(x)
        if mode == "gbt" and (self.meta or {}).get("variance_model") == "log_r2":
            c = float(self.meta["variance_scale_c"])
            x = self.scale.transform(x).withColumn(
                "s", F.greatest(F.sqrt(F.lit(c) * F.exp("log_s2_hat")), F.lit(SIGMA_FLOOR)))
        elif mode == "gbt":
            x = self.scale.transform(x).withColumn("s", F.sqrt(F.greatest(F.col("s2_hat"), F.lit(SIGMA_FLOOR ** 2))))
        else:
            x = x.withColumn("s", F.lit(self.sigma_const))
        return x.drop("features", "occ_raw", "occ_probability", "occ_prediction", "s2_hat", "log_s2_hat")

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self.prep.write().overwrite().save(str(path / "prep"))
        self.occurrence.write().overwrite().save(str(path / "occurrence_gbt"))
        self.location.write().overwrite().save(str(path / "log_amount_gbt"))
        if self.scale is not None:
            self.scale.write().overwrite().save(str(path / "log_variance_gbt"))
        meta = {**(self.meta or {}), "sigma_const": self.sigma_const, "sigma_mode": self.sigma_mode,
                "error_dist": self.error_dist, "quantiles": self.quantiles,
                "features": self.prep.stages[-1].getInputCols(), "sigma_floor": SIGMA_FLOOR}
        (path / "ziln_meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> "ZILNModel":
        meta = json.loads((path / "ziln_meta.json").read_text())
        scale = GBTRegressionModel.load(str(path / "log_variance_gbt")) if (path / "log_variance_gbt").exists() else None
        return cls(PipelineModel.load(str(path / "prep")), GBTClassificationModel.load(str(path / "occurrence_gbt")),
                   GBTRegressionModel.load(str(path / "log_amount_gbt")), scale, meta["sigma_const"],
                   meta["sigma_mode"], meta, meta.get("error_dist", "gaussian"), meta.get("quantiles"))


def fit_ziln(train: DataFrame, *, dry_to_wet: float = 3.0, max_iter: int = 60, max_depth: int = 6,
             step_size: float = 0.05, occ_max_iter: int | None = None, occ_step_size: float | None = None,
             features: list[str] | None = None, work_dir: Path | None = None, seed: int = 5208,
             log=print) -> ZILNModel:
    """`train` must already be restricted to eligible rows with column `y`.

    Spark's GBT fits its first tree to the +-1 labels with weight 1 and then takes plain
    gradient steps, so on rare events the occurrence probabilities only approach the
    calibrated solution after enough iterations; it therefore has its own step size and
    iteration count."""
    gbt = dict(maxIter=max_iter, maxDepth=max_depth, stepSize=step_size, maxBins=128, subsamplingRate=0.8, seed=seed)
    gbt_occ = {**gbt, "maxIter": occ_max_iter or max_iter, "stepSize": occ_step_size or step_size}
    prep = PipelineModel(stages=[
        StringIndexer(inputCol="station_id", outputCol="station_index", handleInvalid="keep").fit(train),
        VectorAssembler(inputCols=features or FEATURES, outputCol="features", handleInvalid="error"),
    ])
    data = prep.transform(train.withColumn("wet", (F.col("y") > 0).cast("double"))).select("features", "wet", "y",
                                                                                          "station_id", "prediction_ts")
    spark = train.sparkSession
    if work_dir is not None:  # materialise once: cuts the multi-year join lineage and keeps memory free
        data.write.mode("overwrite").parquet(str(work_dir / "assembled"))
        data = spark.read.parquet(str(work_dir / "assembled"))
    counts = {r["wet"]: r["count"] for r in data.groupBy("wet").count().collect()}
    n_wet, n_dry = counts.get(1.0, 0), counts.get(0.0, 0)
    q = min(1.0, dry_to_wet * n_wet / n_dry)
    log(f"training rows: wet={n_wet:,} dry={n_dry:,}; dry rows kept at q={q:.4f} with weight 1/q")

    occ_train = data.sampleBy("wet", {0.0: q, 1.0: 1.0}, seed=seed).withColumn(
        "w", F.when(F.col("wet") == 1.0, F.lit(1.0)).otherwise(F.lit(1.0 / q))).cache()
    occurrence = (GBTClassifier(featuresCol="features", labelCol="wet", weightCol="w", predictionCol="occ_prediction", **gbt_occ)
                  .setProbabilityCol("occ_probability").setRawPredictionCol("occ_raw").fit(occ_train))
    occ_train.unpersist()
    log("fitted occurrence model pi(x)")

    wet = (data.filter("wet = 1.0").withColumn("log_y", F.log("y"))
           .withColumn("fold", F.pmod(F.xxhash64("station_id", "prediction_ts"), F.lit(2))).cache())
    loc = lambda: GBTRegressor(featuresCol="features", labelCol="log_y", predictionCol="m", **gbt)  # noqa: E731
    # Cross-fitting: residuals for the variance model come from a location model that did not see the row.
    oof = None
    for f in (0, 1):
        part = loc().fit(wet.filter(F.col("fold") != f)).transform(wet.filter(F.col("fold") == f))
        oof = part if oof is None else oof.unionByName(part)
    oof = oof.withColumn("r2", (F.col("log_y") - F.col("m")) ** 2).select("features", "r2", "log_y", "m")
    if work_dir is not None:
        oof.write.mode("overwrite").parquet(str(work_dir / "oof"))
        oof = spark.read.parquet(str(work_dir / "oof"))
    else:
        oof = oof.cache()
    sigma_const = math.sqrt(oof.agg(F.avg("r2")).first()[0])
    scale, variance_meta, quantiles = fit_variance_and_errors(oof, gbt, sigma_const)
    location = loc().fit(wet)
    oof.unpersist(); wet.unpersist()
    log(f"fitted log-amount model m(x) and variance model; constant sigma={sigma_const:.4f}")
    meta = {"n_wet": n_wet, "n_dry": n_dry, "dry_keep_rate": q, "gbt_params_occurrence": gbt_occ,
            "gbt_params_amount": gbt, **variance_meta}
    return ZILNModel(prep, occurrence, location, scale, sigma_const, "gbt", meta, "gaussian", quantiles)


def fit_variance_and_errors(oof: DataFrame, gbt: dict, sigma_const: float):
    """Variance model and standardised-residual quantile tables from cross-fitted residuals.

    Regressing r^2 directly can give non-positive variances. Under Gaussian errors
    r^2 = s^2 * chi2_1, so log r^2 = log s^2(x) + log chi2_1 and a squared-loss fit of
    log r^2 recovers log s^2(x) up to a constant. The constant is the profile MLE
    c = mean(r^2 / exp(g(x))), so s(x)^2 = c * exp(g(x)) > 0.
    `oof` needs columns features, r2, log_y, m."""
    data = oof.withColumn("log_r2", F.log(F.greatest("r2", F.lit(1e-8))))
    scale = GBTRegressor(featuresCol="features", labelCol="log_r2", predictionCol="log_s2_hat", **gbt).fit(data)
    g = scale.transform(data)
    c = g.agg(F.avg(F.col("r2") / F.exp("log_s2_hat"))).first()[0]
    s_hat = F.greatest(F.sqrt(F.lit(c) * F.exp("log_s2_hat")), F.lit(SIGMA_FLOOR))
    z = g.select(((F.col("log_y") - F.col("m")) / s_hat).alias("z_gbt"),
                 ((F.col("log_y") - F.col("m")) / F.lit(sigma_const)).alias("z_const"))
    qs = z.approxQuantile(["z_gbt", "z_const"], QUANTILE_PROBS, 1e-5)
    quantiles = {"gbt": {"p": QUANTILE_PROBS, "q": qs[0]}, "const": {"p": QUANTILE_PROBS, "q": qs[1]}}
    # Location-dependent error distribution: one table per decile of the cross-fitted m.
    edges = g.approxQuantile("m", [i / M_BINS for i in range(1, M_BINS)], 1e-4)
    zb = g.select(F.col("m"), ((F.col("log_y") - F.col("m")) / s_hat).alias("z_gbt"),
                  ((F.col("log_y") - F.col("m")) / F.lit(sigma_const)).alias("z_const"))
    bin_col = sum((F.col("m") > F.lit(e)).cast("int") for e in edges)
    pct = F.array(*[F.lit(p) for p in BIN_QUANTILE_PROBS])
    rows = (zb.withColumn("bin", bin_col).groupBy("bin")
            .agg(F.percentile_approx("z_gbt", pct, 100000).alias("q_gbt"),
                 F.percentile_approx("z_const", pct, 100000).alias("q_const")).orderBy("bin").collect())
    assert [r["bin"] for r in rows] == list(range(M_BINS)), "every m-decile needs residuals"
    for mode in ("gbt", "const"):
        quantiles[f"{mode}_by_m"] = {"edges": edges, "tables": [{"p": BIN_QUANTILE_PROBS, "q": list(r[f"q_{mode}"])} for r in rows]}
    return scale, {"variance_model": "log_r2", "variance_scale_c": c}, quantiles


def select_on_validation(model: "ZILNModel", validation: DataFrame, log=print) -> dict:
    """Score sigma in {const, gbt} x errors in {gaussian, empirical} on validation rows and keep
    the lowest lattice NLL; mean P(Y > r) vs event rate at 1/5/10 mm is recorded alongside."""
    selection = {}
    for mode in ("const", "gbt"):
        scored = model.transform(validation, sigma_mode=mode).select("y", "pi", "m", "s").cache()
        for dist in ("gaussian", "empirical", "empirical_by_m"):
            cols = [F.avg(f"d.{c}").alias(c) for c in ("nll_lattice", "nll_density", "crps")]
            for r in (1.0, 5.0, 10.0):
                cols += [F.avg(model.exceedance(r, mode, dist)).alias(f"mean_p_gt_{r:g}"),
                         F.avg((F.col("y") > r).cast("double")).alias(f"rate_gt_{r:g}")]
            row = scored.withColumn("d", model.scores("y", mode, dist)).agg(*cols).first().asDict()
            selection[f"{mode}/{dist}"] = row
            log(f"validation, sigma={mode}, errors={dist}: {row}")
        scored.unpersist()
    best = min(selection, key=lambda k: selection[k]["nll_lattice"])
    model.sigma_mode, model.error_dist = best.split("/")
    return selection


def best_f1_threshold(scored: DataFrame, prob_col: str, label_col: str) -> tuple[float, float]:
    """Max-F1 probability cutoff at 0.001 resolution (same rule as select_decision_threshold.py)."""
    bins = (scored.select((F.floor(F.col(prob_col) * 1000) / 1000).alias("t"), F.col(label_col).alias("l"))
            .groupBy("t").agg(F.count("*").alias("n"), F.sum("l").alias("p")).orderBy(F.col("t").desc()).collect())
    total_pos = sum(int(b["p"] or 0) for b in bins)
    tp = pp = 0
    best = (0.0, 1.0)
    for b in bins:
        tp += int(b["p"] or 0); pp += int(b["n"])
        best = max(best, (2 * tp / (total_pos + pp), float(b["t"])))
    return best[1], best[0]
