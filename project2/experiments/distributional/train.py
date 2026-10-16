#!/usr/bin/env python3
"""Train one zero-inflated rainfall family with a shared MLP trunk and save raw head
outputs for the full 2023 validation and 2024 test years.

Identical inputs, architecture, optimiser, data and seed for every family; only the
likelihood (and hence the meaning of the three heads) changes.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import torch
import torch.nn as nn

import dists as D

HERE = Path(__file__).resolve().parent
FEAT = HERE.parents[1] / "data" / "processed" / "dist_features"
RUNS = HERE / "runs"
K = 8
TRAIN_YEARS, VAL_YEAR, TEST_YEAR = list(range(2017, 2023)), 2023, 2024


def lg(x):
    return np.log1p(np.nan_to_num(x, nan=0.0) / D.DELTA)


def featurize(t, stations: dict[str, int]):
    """pyarrow table -> (float32 matrix, station index, target, slot)."""
    c = {name: t.column(name).to_numpy(zero_copy_only=False) for name in t.column_names}
    cols = [lg(c[n]) for n in ("y", "lag1", "lag2", "s3", "s6", "s12", "max12", "s36")]
    cols.append(c["c36"] / 36.0)
    w_sum = 0.0; idw = {n: 0.0 for n in ("y1", "s3", "s12")}; nbmax = np.zeros(len(c["y"])); wet = 0.0; navail = 0.0
    for k in range(1, K + 1):
        avail = c[f"nb{k}_avail"].astype(np.float64)
        for n in ("y1", "s3", "s12"):
            v = np.nan_to_num(c[f"nb{k}_{n}"], nan=0.0)
            cols.append(lg(v))
            idw[n] = idw[n] + avail * v / np.maximum(c[f"nb{k}_dist"], 0.05)
        cols += [avail, np.nan_to_num(c[f"nb{k}_c12ok"], nan=0.0).astype(np.float64),
                 c[f"nb{k}_dist"] / 10.0, c[f"nb{k}_dx"] / 10.0, c[f"nb{k}_dy"] / 10.0]
        w_sum = w_sum + avail / np.maximum(c[f"nb{k}_dist"], 0.05)
        nbmax = np.maximum(nbmax, np.nan_to_num(c[f"nb{k}_s12"], nan=0.0))
        wet = wet + avail * (np.nan_to_num(c[f"nb{k}_y1"], nan=0.0) > 0)
        navail = navail + avail
    for n in ("y1", "s3", "s12"):
        cols.append(lg(np.where(w_sum > 0, idw[n] / np.where(w_sum > 0, w_sum, 1), 0.0)))
    cols += [lg(nbmax), np.where(navail > 0, wet / np.maximum(navail, 1), 0.0), navail / K]
    slot = c["slot"]
    sec = (slot + 8 * 3600) % 86400
    day = ((slot + 8 * 3600) // 86400) % 365.2425
    cols += [np.sin(2 * np.pi * sec / 86400), np.cos(2 * np.pi * sec / 86400),
             np.sin(2 * np.pi * day / 365.2425), np.cos(2 * np.pi * day / 365.2425),
             (c["lat"] - 1.35) / 0.05, (c["lon"] - 103.82) / 0.1]
    X = np.stack(cols, axis=1).astype(np.float32)
    sidx = np.array([stations.get(s, 0) for s in c["station"]], dtype=np.int64)
    return X, sidx, c["target"].astype(np.float32), slot


def load(year, stations, zero_keep=None, rng=None):
    t = pq.read_table(FEAT / f"year={year}.parquet")
    if zero_keep is not None:
        y = t.column("target").to_numpy()
        keep = (y > 0) | (rng.random(len(y)) < zero_keep)
        t = t.filter(keep)
    return featurize(t, stations)


class Net(nn.Module):
    def __init__(self, d_in, n_station, width=256, depth=3, emb=8):
        super().__init__()
        self.emb = nn.Embedding(n_station, emb)
        layers, d = [], d_in + emb
        for _ in range(depth):
            layers += [nn.Linear(d, width), nn.SiLU()]
            d = width
        self.trunk = nn.Sequential(*layers)
        self.head = nn.Linear(width, 3)
        self.glob = nn.Parameter(torch.zeros(()))  # Tweedie: p = 1 + sigmoid(glob)

    def forward(self, x, s):
        return self.head(self.trunk(torch.cat([x, self.emb(s)], 1)))


def init_head(net, family, y_pos_mean, p_pos):
    b = net.head.bias.data
    with torch.no_grad():
        net.head.weight.mul_(0.1)
        if family == "ziln":
            b[:] = torch.tensor([math.log(p_pos / (1 - p_pos)), math.log(0.6), 0.5])
        elif family == "bgamma":
            b[:] = torch.tensor([math.log(p_pos / (1 - p_pos)), math.log(y_pos_mean), -0.5])
        elif family == "cpg":
            b[:] = torch.tensor([math.log(-math.log(1 - p_pos)), 0.0, math.log(y_pos_mean)])
        else:  # tweedie: mu, phi
            b[:] = torch.tensor([math.log(p_pos * y_pos_mean), 0.0, 0.0])


@torch.no_grad()
def predict(net, X, S, dev, bs=65536):
    net.eval()
    out = [net(torch.from_numpy(X[i:i + bs]).to(dev), torch.from_numpy(S[i:i + bs]).to(dev)).float().cpu()
           for i in range(0, len(X), bs)]
    return torch.cat(out).numpy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", choices=D.FAMILIES, required=True)
    ap.add_argument("--seed", type=int, default=5208)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--bs", type=int, default=8192)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--zero-keep", type=float, default=0.2)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    run = RUNS / f"{args.family}{args.tag}_s{args.seed}"
    run.mkdir(parents=True, exist_ok=True)

    import pyarrow.compute as pc
    names = set()
    for yr in TRAIN_YEARS:
        names |= set(pc.unique(pq.read_table(FEAT / f"year={yr}.parquet", columns=["station"]).column("station")).to_pylist())
    stations = {s: i + 1 for i, s in enumerate(sorted(names))}  # 0 = unseen station

    t0 = time.time()
    parts = [load(yr, stations, args.zero_keep, rng) for yr in TRAIN_YEARS]
    X = np.concatenate([p[0] for p in parts]); S = np.concatenate([p[1] for p in parts]); Y = np.concatenate([p[2] for p in parts])
    del parts
    W = np.where(Y > 0, 1.0, 1.0 / args.zero_keep).astype(np.float32)  # inverse inclusion probability
    mu_x, sd_x = X.mean(0), X.std(0) + 1e-6
    X = (X - mu_x) / sd_x
    Xv, Sv, Yv, slot_v = load(VAL_YEAR, stations); Xv = (Xv - mu_x) / sd_x
    vsub = rng.choice(len(Yv), size=min(1_500_000, len(Yv)), replace=False)
    p_pos = float((W * (Y > 0)).sum() / W.sum()); y_pos_mean = float(Y[Y > 0].mean())
    print(f"loaded train={len(Y):,} rows (weighted N={W.sum():,.0f}, P(y>0)={p_pos:.4f}) val={len(Yv):,} "
          f"d={X.shape[1]} stations={len(stations)} in {time.time() - t0:.0f}s", flush=True)

    net = Net(X.shape[1], len(stations) + 1).to(dev)
    init_head(net, args.family, y_pos_mean, p_pos)
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-4)
    steps = args.epochs * math.ceil(len(Y) / args.bs)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=steps, pct_start=0.05)
    Xt, St, Yt, Wt = (torch.from_numpy(a) for a in (X, S, Y, W))
    Xvs, Svs = torch.from_numpy(Xv[vsub]).to(dev), torch.from_numpy(Sv[vsub]).to(dev)
    Yvs = torch.from_numpy(Yv[vsub]).to(dev)
    best, log = (math.inf, None), []
    for ep in range(args.epochs):
        net.train()
        perm = torch.randperm(len(Yt))
        tot, cnt, t1 = 0.0, 0.0, time.time()
        for i in range(0, len(perm), args.bs):
            b = perm[i:i + args.bs]
            x, s, y, w = Xt[b].to(dev), St[b].to(dev), Yt[b].to(dev), Wt[b].to(dev)
            nll = D.torch_nll(args.family, net(x, s), y, net.glob)
            loss = (w * nll).sum() / w.sum()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0)
            opt.step(); sched.step()
            tot += float((w * nll).sum()); cnt += float(w.sum())
        with torch.no_grad():
            net.eval()
            vl = sum(float(D.torch_nll(args.family, net(Xvs[j:j + 65536], Svs[j:j + 65536]), Yvs[j:j + 65536], net.glob).sum())
                     for j in range(0, len(Yvs), 65536)) / len(Yvs)
        extra = f" p={1 + torch.sigmoid(net.glob).item():.4f}" if args.family == "tweedie" else ""
        print(f"[{args.family}] epoch {ep + 1}/{args.epochs} train_nll={tot / cnt:.5f} val_nll={vl:.5f}{extra} "
              f"({time.time() - t1:.0f}s)", flush=True)
        log.append({"epoch": ep + 1, "train_nll": tot / cnt, "val_nll_density": vl})
        if not math.isfinite(vl):
            raise SystemExit("non-finite validation loss")
        if vl < best[0]:
            best = (vl, {k: v.detach().clone() for k, v in net.state_dict().items()})
    net.load_state_dict(best[1])
    torch.save({"state": best[1], "mu_x": mu_x, "sd_x": sd_x, "stations": stations, "args": vars(args)}, run / "model.pt")

    Hv = predict(net, Xv, Sv, dev)
    Xs, Ss, Ys, slot_s = load(TEST_YEAR, stations); Xs = (Xs - mu_x) / sd_x
    Hs = predict(net, Xs, Ss, dev)
    glob = float(net.glob.detach().cpu())
    np.savez_compressed(run / "pred.npz", Hv=Hv, Yv=Yv, slot_v=slot_v, Hs=Hs, Ys=Ys, slot_s=slot_s, glob=glob,
                        unseen_test=(Ss == 0).mean())
    (run / "train_log.json").write_text(json.dumps({"args": vars(args), "log": log, "best_val_nll_density": best[0],
                                                    "glob": glob, "n_train_rows": int(len(Y))}, indent=2))
    print(f"saved {run} (unseen test stations: {(Ss == 0).mean():.4%})", flush=True)


if __name__ == "__main__":
    main()
