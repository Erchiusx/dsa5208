#!/usr/bin/env python3
"""Nonparametric alternative to ZILN: a softmax over rainfall bins on the same MLP trunk.

The 30-minute total is coded as class 0 (y = 0) or class j (EDGES[j-1] < y <= EDGES[j]),
so P(Y > r) for any bin edge r is a sum of class probabilities: monotone in r and free of
any distributional assumption on the wet amount. Dry rows are subsampled and reweighted
exactly as for the parametric families. The 2023/2024 predictions are scored against the
saved ZILN run on identical rows: binned log score, ranked probability score over the
edges, and Brier / ROC / AP / calibration at the report thresholds.
"""
from __future__ import annotations

import json
import math
import time

import numpy as np
import torch
import torch.nn as nn
from scipy.special import ndtr
from scipy.stats import rankdata

from train import FEAT, RUNS, TRAIN_YEARS, VAL_YEAR, TEST_YEAR, Net, load, predict
import pyarrow.parquet as pq
import pyarrow.compute as pc
import dists as D

EDGES = np.array([0.2, 0.4, 0.6, 0.8, 1.0, 1.4, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0, 50.0, np.inf])
K = len(EDGES) + 1
REPORT = (1.0, 2.0, 5.0, 10.0, 20.0)


def to_class(y):
    return np.where(y <= 0, 0, 1 + np.searchsorted(EDGES, y, side="left")).astype(np.int64)


def ziln_bins(H):
    P = D.np_params("ziln", H)
    cdf = np.concatenate([np.zeros((len(H), 1)), ndtr((np.log(EDGES[:-1])[None] - P["m"][:, None]) / P["s"][:, None]),
                          np.ones((len(H), 1))], axis=1)
    return np.concatenate([(1 - P["pi"])[:, None], P["pi"][:, None] * np.diff(cdf, axis=1)], axis=1)


def metrics(prob, cls, day):
    """prob: (n, K) class probabilities; returns scores and per-day sums for bootstrapping."""
    prob = np.clip(prob, 1e-12, 1.0)
    logs = -np.log(prob[np.arange(len(cls)), cls])
    surv = 1.0 - np.cumsum(prob, axis=1)[:, :-1]          # P(Y > EDGES[j]) for j = 0..K-2
    obs = cls[:, None] > np.arange(0, K - 1)[None]   # column i: Y > EDGES[i-1] (column 0: Y > 0)
    rps = ((surv - obs) ** 2).sum(1)
    out = {"log_score": float(logs.mean()), "rps": float(rps.mean())}
    for r in REPORT:
        j = int(np.where(EDGES == r)[0][0]) + 1; p, l = surv[:, j], obs[:, j]
        order = np.argsort(-p, kind="mergesort"); ls = l[order]
        ap = float((np.cumsum(ls) / np.arange(1, len(ls) + 1))[ls].sum() / ls.sum())
        n1 = l.sum(); n0 = len(l) - n1
        roc = float((rankdata(p)[l].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))
        out[f"{r:g}mm"] = {"brier": float(((p - l) ** 2).mean()), "roc_auc": roc, "avg_precision": ap,
                           "pred_over_obs": float(p.mean() / l.mean())}
    days, inv = np.unique(day, return_inverse=True)
    return out, {"log_score": np.bincount(inv, logs), "rps": np.bincount(inv, rps), "n": np.bincount(inv)}


def main():
    seed, epochs, bs, lr, zero_keep = 5208, 8, 8192, 2e-3, 0.2
    torch.manual_seed(seed); rng = np.random.default_rng(seed)
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    run = RUNS / f"binned_s{seed}"; run.mkdir(parents=True, exist_ok=True)

    names = set()
    for yr in TRAIN_YEARS:
        names |= set(pc.unique(pq.read_table(FEAT / f"year={yr}.parquet", columns=["station"]).column("station")).to_pylist())
    stations = {s: i + 1 for i, s in enumerate(sorted(names))}
    parts = [load(yr, stations, zero_keep, rng) for yr in TRAIN_YEARS]
    X = np.concatenate([p[0] for p in parts]); S = np.concatenate([p[1] for p in parts]); Y = np.concatenate([p[2] for p in parts])
    del parts
    W = np.where(Y > 0, 1.0, 1.0 / zero_keep).astype(np.float32)
    mu_x, sd_x = X.mean(0), X.std(0) + 1e-6
    X = (X - mu_x) / sd_x
    Xv, Sv, Yv, slot_v = load(VAL_YEAR, stations); Xv = (Xv - mu_x) / sd_x
    C, Cv = to_class(Y), to_class(Yv)
    vsub = rng.choice(len(Yv), size=min(1_500_000, len(Yv)), replace=False)

    net = Net(X.shape[1], len(stations) + 1).to(dev)
    net.head = nn.Linear(net.head.in_features, K).to(dev)
    prior = np.bincount(C, weights=W, minlength=K) / W.sum()
    with torch.no_grad():
        net.head.weight.mul_(0.1); net.head.bias.copy_(torch.tensor(np.log(np.maximum(prior, 1e-7)), dtype=torch.float32))
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=epochs * math.ceil(len(Y) / bs), pct_start=0.05)
    Xt, St, Ct, Wt = (torch.from_numpy(a) for a in (X, S, C, W))
    Xvs, Svs, Cvs = (torch.from_numpy(a[vsub]).to(dev) for a in (Xv, Sv, Cv))
    ce = nn.CrossEntropyLoss(reduction="none")
    best = (math.inf, None)
    for ep in range(epochs):
        net.train(); perm = torch.randperm(len(Ct)); t1 = time.time()
        for i in range(0, len(perm), bs):
            b = perm[i:i + bs]
            x, s, c, w = Xt[b].to(dev), St[b].to(dev), Ct[b].to(dev), Wt[b].to(dev)
            loss = (w * ce(net(x, s), c)).sum() / w.sum()
            opt.zero_grad(set_to_none=True); loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0); opt.step(); sched.step()
        with torch.no_grad():
            net.eval()
            vl = sum(float(ce(net(Xvs[j:j + 65536], Svs[j:j + 65536]), Cvs[j:j + 65536]).sum())
                     for j in range(0, len(Cvs), 65536)) / len(Cvs)
        print(f"[binned] epoch {ep + 1}/{epochs} val_log_score={vl:.5f} ({time.time() - t1:.0f}s)", flush=True)
        if vl < best[0]:
            best = (vl, {k: v.detach().clone() for k, v in net.state_dict().items()})
    net.load_state_dict(best[1])
    torch.save({"state": best[1], "mu_x": mu_x, "sd_x": sd_x, "stations": stations, "edges": EDGES}, run / "model.pt")

    ref = np.load(RUNS / "ziln_s5208" / "pred.npz")
    report = {}
    for split, year, Hz in (("validation_2023", VAL_YEAR, ref["Hv"]), ("test_2024", TEST_YEAR, ref["Hs"])):
        Xe, Se, Ye, slot = load(year, stations); Xe = (Xe - mu_x) / sd_x
        logits = predict(net, Xe, Se, dev)
        pb = np.exp(logits - logits.max(1, keepdims=True)); pb /= pb.sum(1, keepdims=True)
        cls, day = to_class(Ye), (slot + 8 * 3600) // 86400
        mb, db = metrics(pb, cls, day)
        mz, dz = metrics(ziln_bins(Hz), cls, day)
        boot = {}
        for key in ("log_score", "rps"):
            diff = (db[key] - dz[key]); n = db["n"]
            reps = [diff[idx].sum() / n[idx].sum() for idx in (rng.integers(0, len(n), len(n)) for _ in range(500))]
            boot[key] = {"binned_minus_ziln": float(diff.sum() / n.sum()), "ci95": [float(np.percentile(reps, 2.5)), float(np.percentile(reps, 97.5))]}
        report[split] = {"binned": mb, "ziln": mz, "day_block_bootstrap": boot}
        print(split, json.dumps(report[split], indent=1), flush=True)
    (run / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
