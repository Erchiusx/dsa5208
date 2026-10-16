"""Monte-Carlo / quadrature checks of every closed form and series in dists.py."""
import numpy as np, torch
from scipy import integrate, special as sp
import dists as D

rng = np.random.default_rng(0)

def mc_crps(x, y):
    xs = np.sort(x); M = xs.size
    gini = 2 * np.sum((2 * np.arange(1, M + 1) - M - 1) * xs) / (M * M)   # E|X-X'|
    return np.abs(x - y).mean() - 0.5 * gini

def sample(family, P, i, M):
    if family in ("ziln", "bgamma"):
        z = (np.exp(P["m"][i] + P["s"][i] * rng.standard_normal(M)) if family == "ziln"
             else rng.gamma(P["k"][i], P["th"][i], M))
        return np.where(rng.random(M) < P["pi"][i], z, 0.0)
    n = rng.poisson(P["lam"][i], M)
    out = np.zeros(M); nz = n > 0
    out[nz] = rng.gamma(n[nz] * P["alpha"][i], P["th"][i])
    return out

cases = {
 "ziln":   np.array([[ -1.0, np.log(0.6), 0.5], [2.0, 1.0, -1.0], [0.0, -1.0, 1.5]]),
 "bgamma": np.array([[ -1.0, np.log(0.6), -1.0], [2.0, 1.5, 1.0], [0.0, 0.0, -3.0]]),
 "cpg":    np.array([[np.log(0.07), 0.3, np.log(3.0)], [np.log(2.5), -1.5, np.log(1.0)], [np.log(8.0), 0.5, np.log(0.3)]]),
}
ys = np.array([0.0, 0.2, 0.6, 1.0, 3.4, 12.0])
worst = 0
for fam, H in cases.items():
    P = D.np_params(fam, np.repeat(H, ys.size, 0))
    y = np.tile(ys, H.shape[0])
    S = D.scores(fam, P, y)
    for i in range(H.shape[0]):
        x = sample(fam, P, i * ys.size, 2_000_000)
        for j, yv in enumerate(ys):
            r = i * ys.size + j
            mc = mc_crps(x, yv)
            rel = abs(S["crps"][r] - mc) / max(mc, 1e-3)
            worst = max(worst, rel)
            if rel > 5e-3: print(f"CRPS MISMATCH {fam} case{i} y={yv}: exact={S['crps'][r]:.5f} mc={mc:.5f}")
        for rr in (1.0, 5.0):
            pe = S[f"p_gt_{rr:g}"][i * ys.size]; pm = (x > rr).mean()
            if abs(pe - pm) > 3e-3: print(f"EXCEED MISMATCH {fam} case{i} r={rr}: {pe:.5f} vs {pm:.5f}")
print(f"CRPS worst relative error vs MC (2e6 draws): {worst:.2e}")

# lattice probabilities sum to 1; density integrates to P(Y>0)
for fam, H in cases.items():
    for i in range(H.shape[0]):
        ks = np.arange(0, 4000); yk = ks * D.DELTA
        P = D.np_params(fam, np.repeat(H[i:i+1], ks.size, 0))
        s = np.exp(-D.scores(fam, P, yk)["nll_lattice"]).sum()
        P1 = D.np_params(fam, H[i:i+1])
        if fam == "cpg":
            f = lambda t: np.exp(D.cpg_logpdf_pos(P1, np.array([t])))[0]; p0 = np.exp(-P1["lam"][0])
        else:
            f = lambda t: P1["pi"][0] * np.exp(D.pos_logpdf(fam, P1, np.array([t])))[0]; p0 = 1 - P1["pi"][0]
        tot = integrate.quad(f, 0, 1, limit=400)[0] + integrate.quad(f, 1, np.inf, limit=400)[0]
        print(f"{fam} case{i}: sum lattice probs={s:.8f}  P0+int(density)={p0 + tot:.8f}")

# CPG density: windowed Dunn-Smyth sum (torch 128 terms, numpy 512) vs brute force n=1..20000
H = np.array([[np.log(0.07), 0.3, np.log(3.0)], [np.log(2.5), -1.5, np.log(1.0)], [np.log(8.0), 0.5, np.log(0.3)],
              [np.log(30.0), -3.0, np.log(0.05)]])
for i in range(H.shape[0]):
    for yv in (0.2, 1.0, 10.0, 70.0):
        P = D.np_params("cpg", H[i:i+1]); lam, al, th = P["lam"][0], P["alpha"][0], P["th"][0]
        n = np.arange(1, 20001); a = n * al
        brute = sp.logsumexp(-lam + n*np.log(lam) - sp.gammaln(n+1) + (a-1)*np.log(yv) - yv/th - sp.gammaln(a) - a*np.log(th))
        npw = D.cpg_logpdf_pos(P, np.array([yv]))[0]
        tw = D.cpg_logpdf_pos_torch(torch.tensor([yv], dtype=torch.float64), torch.tensor([lam], dtype=torch.float64),
                                    torch.tensor([al], dtype=torch.float64), torch.tensor([th], dtype=torch.float64)).item()
        if max(abs(brute - npw), abs(brute - tw)) > 1e-6:
            print(f"CPG logpdf window error case{i} y={yv}: brute={brute:.6f} np512={npw:.6f} torch128={tw:.6f}")
print("CPG density window check done")

# torch NLL == numpy density NLL
for fam in ("ziln", "bgamma", "cpg", "tweedie"):
    h = rng.normal(0, 1, (50, 3)); y = np.where(rng.random(50) < 0.5, 0, rng.gamma(1, 2, 50)).astype(np.float64)
    g = 0.3
    tn = D.torch_nll(fam, torch.tensor(h), torch.tensor(y), torch.tensor(g, dtype=torch.float64)).numpy()
    nn = D.scores(fam, D.np_params(fam, h, g), y)["nll_density"]
    print(f"{fam}: max |torch - numpy| density NLL = {np.abs(tn - nn).max():.2e}")
