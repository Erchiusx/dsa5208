#!/usr/bin/env python3
"""Score saved runs on the full 2024 test year (selection-only use of 2023).

Reports mean density NLL, lattice NLL, CRPS, PIT calibration, exceedance metrics, and
day-block bootstrap CIs for differences between families.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

import dists as D

HERE = Path(__file__).resolve().parent
FEAT = HERE.parents[1] / "data" / "processed" / "dist_features"
RUNS = HERE / "runs"
THRESH = (0.0, 1.0, 5.0, 10.0)
GBT = {"roc_auc": 0.9348873833689924, "pr_auc": 0.6052006336853639, "f1": 0.5939159703394814,
       "brier": 0.0763423779612443, "bss": -2.0479406554040747}


def auc_roc(p, y):
    order = np.argsort(p, kind="mergesort")
    ps, ys = p[order], y[order]
    # midranks for ties
    _, inv, cnt = np.unique(ps, return_inverse=True, return_counts=True)
    csum = np.cumsum(cnt); ranks = (csum - (cnt - 1) / 2.0)[inv]
    npos = ys.sum(); nneg = len(ys) - npos
    return float((ranks[ys == 1].sum() - npos * (npos + 1) / 2) / (npos * nneg))


def pr_curve_areas(p, y):
    """Trapezoidal area under (recall, precision) at distinct scores (Spark's areaUnderPR
    convention, without its 1000-bin downsampling) and average precision."""
    order = np.argsort(-p, kind="mergesort")
    ps, ys = p[order], y[order]
    last = np.r_[np.nonzero(np.diff(ps))[0], len(ps) - 1]
    tp = np.cumsum(ys)[last]; fp = (last + 1) - tp
    prec = tp / (tp + fp); rec = tp / ys.sum()
    rec0 = np.r_[0.0, rec]; prec0 = np.r_[prec[0], prec]
    trap = float(np.sum((rec0[1:] - rec0[:-1]) * (prec0[1:] + prec0[:-1]) / 2))
    ap = float(np.sum((rec0[1:] - rec0[:-1]) * prec))
    return trap, ap


def best_f1_threshold(p, y):
    b = np.floor(p * 1000) / 1000
    vals, inv = np.unique(b, return_inverse=True)
    pos = np.bincount(inv, weights=y); tot = np.bincount(inv)
    tp = np.cumsum(pos[::-1]); pp = np.cumsum(tot[::-1])
    f1 = 2 * tp / (y.sum() + pp)
    i = int(np.argmax(f1))
    return float(vals[::-1][i]), float(f1[i])


def f1_at(p, y, t):
    pred = p >= t
    tp = float((pred & (y == 1)).sum()); fp = float((pred & (y == 0)).sum()); fn = float((~pred & (y == 1)).sum())
    pr = tp / (tp + fp) if tp + fp else 0.0; rc = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": pr, "recall": rc, "f1": 2 * pr * rc / (pr + rc) if pr + rc else 0.0}


def climatology(y_test):
    """Unconditional 2017-2022 empirical distribution: lattice NLL, CRPS, exceedance probs."""
    ytr = np.concatenate([pq.read_table(FEAT / f"year={yr}.parquet", columns=["target"]).column("target").to_numpy()
                          for yr in range(2017, 2023)])
    kt = np.round(ytr / D.DELTA).astype(np.int64)
    freq = np.bincount(kt, minlength=int(np.round(y_test.max() / D.DELTA)) + 2).astype(np.float64) + 0.5
    freq /= freq.sum()
    ks = np.round(y_test / D.DELTA).astype(np.int64)
    nll_lat = -np.log(freq[np.minimum(ks, len(freq) - 1)])
    vals, cnt = np.unique(ytr, return_counts=True)
    w = cnt / cnt.sum(); cw = np.cumsum(w); cwx = np.cumsum(w * vals); mean = cwx[-1]
    # E|X-X'| = 2 sum_i w_i x_i (2 F(x_i) - w_i - 1)  for a discrete distribution sorted ascending
    gini = 2 * np.sum(w * vals * (2 * cw - w - 1))
    j = np.searchsorted(vals, y_test, side="right") - 1
    Fy = np.where(j >= 0, cw[np.maximum(j, 0)], 0.0); Sy = np.where(j >= 0, cwx[np.maximum(j, 0)], 0.0)
    eabs = y_test * Fy - Sy + (mean - Sy) - y_test * (1 - Fy)
    crps = eabs - 0.5 * gini
    probs = {r: float((ytr > r).mean()) for r in THRESH}
    return {"nll_lattice": nll_lat, "crps": crps}, probs


def day_bootstrap(per_row: dict[str, np.ndarray], day: np.ndarray, ref: str, B=2000, seed=0):
    uniq, inv = np.unique(day, return_inverse=True)
    n_day = np.bincount(inv).astype(np.float64)
    sums = {k: np.bincount(inv, weights=v) for k, v in per_row.items()}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uniq), (B, len(uniq)))
    cnt = n_day[idx].sum(1)
    out = {}
    for k, s in sums.items():
        if k == ref:
            continue
        d = (s[idx].sum(1) - sums[ref][idx].sum(1)) / cnt
        out[k] = {"mean_diff_vs_" + ref: float((s.sum() - sums[ref].sum()) / n_day.sum()),
                  "ci95": [float(np.quantile(d, 0.025)), float(np.quantile(d, 0.975))]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--out", default=str(HERE / "results"))
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(exist_ok=True)
    res, per_row = {}, {m: {} for m in ("nll_density", "nll_lattice", "crps")}
    ys = day = None
    rng = np.random.default_rng(1)
    for name in args.runs:
        fam = name.split("_s")[0].split("-")[0]
        z = np.load(RUNS / name / "pred.npz")
        glob = float(z["glob"])
        ys_, yv = z["Ys"].astype(np.float64), z["Yv"].astype(np.float64)
        if ys is None:
            ys, day = ys_, (z["slot_s"] + 8 * 3600) // 86400
        assert np.array_equal(ys, ys_), "runs must share the same test rows"
        S = D.scores(fam, D.np_params(fam, z["Hs"], glob), ys, THRESH)
        Sv = D.scores(fam, D.np_params(fam, z["Hv"], glob), yv, (1.0,))
        r = {"family": fam, "test_rows": int(len(ys))}
        for m in per_row:
            per_row[m][name] = S[m]
            r[m] = float(S[m].mean())
            r[m + "_val"] = float(Sv[m].mean())
        u = S["F_lo"] + rng.random(len(ys)) * (S["F_hi"] - S["F_lo"])
        hist = np.histogram(u, bins=10, range=(0, 1))[0] / len(u)
        r["pit_hist"] = hist.tolist(); r["pit_max_abs_dev"] = float(np.abs(hist - 0.1).max())
        r["exceedance"] = {}
        for t in THRESH:
            p = S[f"p_gt_{t:g}"]; lab = (ys > t).astype(np.float64)
            trap, apr = pr_curve_areas(p, lab)
            r["exceedance"][f"{t:g}"] = {"brier": float(np.mean((p - lab) ** 2)), "roc_auc": auc_roc(p, lab),
                                         "pr_auc_trapz": trap, "avg_precision": apr,
                                         "mean_pred": float(p.mean()), "obs_freq": float(lab.mean())}
        pv, labv = Sv["p_gt_1"], (yv > 1.0).astype(np.float64)
        thr, f1v = best_f1_threshold(pv, labv)
        r["f1_1mm"] = {"threshold_selected_on_2023": thr, "val_f1": f1v, **f1_at(S["p_gt_1"], (ys > 1.0).astype(np.float64), thr)}
        if fam == "tweedie":
            r["tweedie_power"] = 1.0 + float(np.clip(1 / (1 + np.exp(-glob)), 0.01, 0.99))
        res[name] = r
        print(json.dumps({k: v for k, v in r.items() if k not in ("pit_hist",)}, indent=None)[:900], flush=True)

    clim, clim_p = climatology(ys)
    res["climatology"] = {"nll_lattice": float(clim["nll_lattice"].mean()), "crps": float(clim["crps"].mean()),
                          "exceedance": {f"{t:g}": {"brier": float(np.mean((clim_p[t] - (ys > t)) ** 2)), "p": clim_p[t]}
                                         for t in THRESH}}
    for name in args.runs:
        for t in THRESH:
            e = res[name]["exceedance"][f"{t:g}"]
            e["bss"] = 1 - e["brier"] / res["climatology"]["exceedance"][f"{t:g}"]["brier"]
        res[name]["crps_skill"] = 1 - res[name]["crps"] / res["climatology"]["crps"]
    best = {m: min(args.runs, key=lambda n: res[n][m]) for m in per_row}
    res["bootstrap_by_day"] = {m: {"reference": best[m], **day_bootstrap(per_row[m], day, best[m])} for m in per_row}
    res["gbt_reference_2024"] = GBT
    (out / "results.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res["bootstrap_by_day"], indent=1))
    print(json.dumps(res["climatology"], indent=1))


if __name__ == "__main__":
    main()
