"""Zero-inflated rainfall distributions: torch log-likelihoods for training and
float64 numpy/scipy scoring (density NLL, lattice NLL, CRPS, exceedance probability).

Families (all put a point mass at 0 and a density on (0, inf)):
  ziln   : P(0)=1-pi, Y|Y>0 ~ LogNormal(m, s)
  bgamma : P(0)=1-pi, Y|Y>0 ~ Gamma(shape k, scale th)
  tweedie: compound Poisson-Gamma with global power p; heads give mu(x), phi(x)
  cpg    : compound Poisson-Gamma with all of lambda, alpha, theta depending on x
           (= Tweedie with x-dependent mu, phi and p)
For the compound Poisson-Gamma, Y = sum_{i<=N} G_i, N ~ Poisson(lam), G_i ~ Gamma(alpha, theta),
so P(Y=0) = exp(-lam) and Y | N=n ~ Gamma(n*alpha, theta).
"""
from __future__ import annotations

import math

import numpy as np
import torch
import torch.nn.functional as F
from scipy import special as sp
from scipy import stats

FAMILIES = ("ziln", "bgamma", "tweedie", "cpg")
DELTA = 0.2  # nominal tipping-bucket resolution (mm)
LOG_SQRT_2PI = 0.5 * math.log(2 * math.pi)


# ----------------------------------------------------------------------------- torch
def _pos(h, floor=1e-3):
    return F.softplus(h) + floor


def torch_params(family: str, h: torch.Tensor, glob: torch.Tensor | None = None) -> dict:
    h = h.clamp(-20, 20)
    if family == "ziln":
        return {"logit": h[:, 0], "m": h[:, 1], "s": _pos(h[:, 2], 1e-2)}
    if family == "bgamma":
        k = _pos(h[:, 2], 1e-2)
        return {"logit": h[:, 0], "k": k, "th": torch.exp(h[:, 1]) / k}
    if family == "cpg":
        return {"lam": torch.exp(h[:, 0]), "alpha": _pos(h[:, 1], 1e-2), "th": torch.exp(h[:, 2])}
    if family == "tweedie":
        p = 1.0 + torch.sigmoid(glob).clamp(0.01, 0.99)
        mu, phi = torch.exp(h[:, 0]), torch.exp(h[:, 1])
        lam = mu.pow(2 - p) / (phi * (2 - p))
        alpha = (2 - p) / (p - 1)
        th = phi * (p - 1) * mu.pow(p - 1)
        return {"lam": lam, "alpha": alpha.expand_as(lam), "th": th, "p": p}
    raise ValueError(family)


def cpg_logpdf_pos_torch(y, lam, alpha, th, nterms: int = 128):
    """log density of the compound Poisson-Gamma at y > 0, summing a window of
    `nterms` Poisson counts centred on the Dunn-Smyth mode j* = lam (y/mu)^(2-p)."""
    mu = lam * alpha * th
    jstar = lam * (y / mu).pow(alpha / (alpha + 1))
    start = torch.clamp(torch.round(jstar.detach()) - nterms // 2, min=1.0)
    n = start[:, None] + torch.arange(nterms, device=y.device, dtype=y.dtype)[None, :]
    a = n * alpha[:, None]
    logy = torch.log(y)[:, None]
    terms = (-lam[:, None] + n * torch.log(lam)[:, None] - torch.lgamma(n + 1)
             + (a - 1) * logy - (y / th)[:, None] - torch.lgamma(a) - a * torch.log(th)[:, None])
    return torch.logsumexp(terms, dim=1)


def torch_nll(family: str, h: torch.Tensor, y: torch.Tensor, glob=None) -> torch.Tensor:
    """Per-row negative log-likelihood w.r.t. (point mass at 0) + Lebesgue on (0, inf)."""
    P = torch_params(family, h, glob)
    pos = y > 0
    ysafe = torch.where(pos, y, torch.ones_like(y))
    if family in ("ziln", "bgamma"):
        log_pi = F.logsigmoid(P["logit"])
        log_1mpi = F.logsigmoid(-P["logit"])
        if family == "ziln":
            z = (torch.log(ysafe) - P["m"]) / P["s"]
            lp = -torch.log(ysafe) - torch.log(P["s"]) - LOG_SQRT_2PI - 0.5 * z * z
        else:
            k, th = P["k"], P["th"]
            lp = (k - 1) * torch.log(ysafe) - ysafe / th - torch.lgamma(k) - k * torch.log(th)
        return -torch.where(pos, log_pi + lp, log_1mpi)
    lam = P["lam"]
    lp = cpg_logpdf_pos_torch(ysafe, lam, P["alpha"], P["th"])
    return -torch.where(pos, lp, -lam)


# ----------------------------------------------------------------------------- numpy
def np_params(family: str, h: np.ndarray, glob: float | None = None) -> dict:
    h = np.clip(h.astype(np.float64), -20, 20)
    sp_ = lambda x, f: np.logaddexp(0, x) + f  # noqa: E731
    if family == "ziln":
        return {"pi": sp.expit(h[:, 0]), "m": h[:, 1], "s": sp_(h[:, 2], 1e-2)}
    if family == "bgamma":
        k = sp_(h[:, 2], 1e-2)
        return {"pi": sp.expit(h[:, 0]), "k": k, "th": np.exp(h[:, 1]) / k}
    if family == "cpg":
        return {"lam": np.exp(h[:, 0]), "alpha": sp_(h[:, 1], 1e-2), "th": np.exp(h[:, 2])}
    if family == "tweedie":
        p = 1.0 + float(np.clip(sp.expit(glob), 0.01, 0.99))
        mu, phi = np.exp(h[:, 0]), np.exp(h[:, 1])
        return {"lam": mu ** (2 - p) / (phi * (2 - p)), "alpha": np.full_like(mu, (2 - p) / (p - 1)),
                "th": phi * (p - 1) * mu ** (p - 1), "p": p}
    raise ValueError(family)


def kind(family: str) -> str:
    return "hurdle" if family in ("ziln", "bgamma") else "cpg"


# --- hurdle positive parts --------------------------------------------------------
def pos_cdf(family, P, z):
    z = np.asarray(z, dtype=np.float64)
    if family == "ziln":
        with np.errstate(divide="ignore"):
            return sp.ndtr((np.log(z) - P["m"]) / P["s"])
    return sp.gammainc(P["k"], z / P["th"])


def pos_sf(family, P, z):
    z = np.asarray(z, dtype=np.float64)
    if family == "ziln":
        with np.errstate(divide="ignore"):
            return sp.ndtr(-(np.log(z) - P["m"]) / P["s"])
    return sp.gammaincc(P["k"], z / P["th"])


def pos_logpdf(family, P, y):
    if family == "ziln":
        z = (np.log(y) - P["m"]) / P["s"]
        return -np.log(y) - np.log(P["s"]) - LOG_SQRT_2PI - 0.5 * z * z
    k, th = P["k"], P["th"]
    return (k - 1) * np.log(y) - y / th - sp.gammaln(k) - k * np.log(th)


def pos_abs_dev(family, P, y):
    """E|Z - y|, E Z and E|Z - Z'| for the positive part."""
    y = np.asarray(y, dtype=np.float64)
    if family == "ziln":
        m, s = P["m"], P["s"]
        ez = np.exp(m + 0.5 * s * s)
        with np.errstate(divide="ignore"):
            ly = np.log(y)
        cdf = sp.ndtr((ly - m) / s)
        partial = ez * sp.ndtr((ly - m - s * s) / s)
        gini = 2 * ez * (2 * sp.ndtr(s / math.sqrt(2)) - 1)
    else:
        k, th = P["k"], P["th"]
        ez = k * th
        cdf = sp.gammainc(k, y / th)
        partial = ez * sp.gammainc(k + 1, y / th)
        gini = 2 * th * np.exp(sp.gammaln(k + 0.5) - sp.gammaln(k)) / math.sqrt(math.pi)
    return ez - y + 2 * (y * cdf - partial), ez, gini


# --- compound Poisson-Gamma -------------------------------------------------------
def _cpg_N(lam, tol=1e-12):
    return (stats.poisson.isf(tol, lam) + 2).astype(np.int64)


def _groups(N, sizes=(4, 8, 16, 32, 64, 128, 256, 512, 1024)):
    """Yield (row_index, nmax) buckets so per-row series are vectorised."""
    lo = 0
    for s in sizes:
        idx = np.nonzero((N > lo) & (N <= s))[0]
        if idx.size:
            yield idx, s
        lo = s
    idx = np.nonzero(N > sizes[-1])[0]
    if idx.size:
        raise ValueError(f"{idx.size} rows need > {sizes[-1]} Poisson terms (max lam={N.max()})")


def cpg_cdf(P, z, tol=1e-12):
    """F(z) for z >= 0 (array aligned with rows); also returns survival 1-F computed stably."""
    lam, alpha, th = P["lam"], P["alpha"], P["th"]
    z = np.broadcast_to(np.asarray(z, dtype=np.float64), lam.shape)
    cdf = np.exp(-lam).copy()
    sf = -np.expm1(-lam)  # P(N>=1); subtract mass below z
    N = _cpg_N(lam, tol)
    cdf_pos = np.zeros_like(lam)
    sf_pos = np.zeros_like(lam)
    for idx, nmax in _groups(N):
        n = np.arange(1, nmax + 1)[None, :]
        pn = stats.poisson.pmf(n, lam[idx, None])
        a = n * alpha[idx, None]
        x = (z[idx] / th[idx])[:, None]
        cdf_pos[idx] = (pn * sp.gammainc(a, x)).sum(1)
        sf_pos[idx] = (pn * sp.gammaincc(a, x)).sum(1)
    return cdf + cdf_pos, sf_pos  # sf: P(Y > z) for z > 0


def cpg_logpdf_pos(P, y, window=512):
    lam, alpha, th = P["lam"], P["alpha"], P["th"]
    mu = lam * alpha * th
    jstar = lam * (y / mu) ** (alpha / (alpha + 1))
    start = np.maximum(np.round(jstar) - window // 2, 1)
    out = np.empty_like(y)
    for c in range(0, y.size, 40_000):
        sl = slice(c, c + 40_000)
        n = start[sl, None] + np.arange(window)[None, :]
        a = n * alpha[sl, None]
        t = (-lam[sl, None] + n * np.log(lam[sl, None]) - sp.gammaln(n + 1) + (a - 1) * np.log(y[sl, None])
             - (y[sl] / th[sl])[:, None] - sp.gammaln(a) - a * np.log(th[sl, None]))
        out[sl] = sp.logsumexp(t, axis=1)
    return out


def cpg_crps(P, y, tol=1e-12):
    """Exact CRPS = E|X-y| - E|X-X'|/2 via Poisson series; for n, m >= 1,
    E|G_a - G_b| = (a+b) th E|2B-1| with B ~ Beta(a, b)."""
    lam, alpha, th = P["lam"], P["alpha"], P["th"]
    N = _cpg_N(lam, tol)
    out = np.empty_like(y)
    for idx, nmax in _groups(N):
        n = np.arange(0, nmax + 1)[None, :]
        pn = stats.poisson.pmf(n, lam[idx, None])
        al, t, yy = alpha[idx, None], th[idx, None], y[idx, None]
        a = n * al
        x = yy / t
        with np.errstate(invalid="ignore"):
            e = np.where(n == 0, yy, a * t - yy + 2 * (yy * sp.gammainc(np.maximum(a, 1e-300), x)
                                                   - a * t * sp.gammainc(a + 1, x)))
        e_abs = (pn * e).sum(1)
        # pairwise E|X - X'| over (n, m) with n, m in 0..nmax; done in row chunks to bound memory
        gini = np.zeros(idx.size)
        for c in range(0, idx.size, max(1, 4_000_000 // (nmax + 1) ** 2)):
            sl = slice(c, c + max(1, 4_000_000 // (nmax + 1) ** 2))
            A = a[sl][:, :, None]; B = a[sl][:, None, :]
            S = A + B
            with np.errstate(invalid="ignore", divide="ignore"):
                frac = np.where(S > 0, (A - B) / np.where(S > 0, S, 1), 0.0)
                Ia = sp.betainc(np.maximum(A, 1e-300), np.maximum(B, 1e-300), 0.5)
                Ia1 = sp.betainc(A + 1, np.maximum(B, 1e-300), 0.5)
                e2b = frac + 2 * Ia - 4 * np.where(S > 0, A / np.where(S > 0, S, 1), 0) * Ia1
            D = S * t[sl][:, :, None] * e2b
            # rows/cols with a zero count: |G - 0| = G -> mean a*th
            D = np.where(A == 0, B * t[sl][:, :, None], D)
            D = np.where(B == 0, A * t[sl][:, :, None], D)
            D = np.where((A == 0) & (B == 0), 0.0, D)
            w = pn[sl][:, :, None] * pn[sl][:, None, :]
            gini[sl] = (w * D).sum((1, 2))
        out[idx] = e_abs - 0.5 * gini
    return out


# ----------------------------------------------------------------------------- scores
def scores(family: str, P: dict, y: np.ndarray, thresholds=(0.0, 1.0, 5.0, 10.0)) -> dict:
    """Per-row density NLL, lattice NLL, CRPS and exceedance probabilities."""
    y = y.astype(np.float64)
    pos = y > 0
    k = np.round(y / DELTA)
    lo = np.where(k == 0, 0.0, (k - 0.5) * DELTA)
    hi = (k + 0.5) * DELTA
    out = {}
    if kind(family) == "hurdle":
        pi = P["pi"]
        dens = np.where(pos, -np.log(pi) - pos_logpdf(family, P, np.where(pos, y, 1.0)), -np.log1p(-pi))
        # lattice mass: k=0 bin is {0} u (0, 0.1); others [(k-1/2)d, (k+1/2)d)
        g_lo_cdf, g_hi_cdf = pos_cdf(family, P, lo), pos_cdf(family, P, hi)
        g_lo_sf, g_hi_sf = pos_sf(family, P, lo), pos_sf(family, P, hi)
        mass_pos = np.where(g_hi_cdf < 0.5, g_hi_cdf - g_lo_cdf, g_lo_sf - g_hi_sf)
        lat = np.where(k == 0, (1 - pi) + pi * g_hi_cdf, pi * mass_pos)
        F_hi = (1 - pi) + pi * g_hi_cdf
        F_lo = np.where(k == 0, 0.0, (1 - pi) + pi * g_lo_cdf)
        eabs, ez, gini = pos_abs_dev(family, P, y)
        crps = (1 - pi) * y + pi * eabs - pi * (1 - pi) * ez - 0.5 * pi * pi * gini
        for r in thresholds:
            out[f"p_gt_{r:g}"] = pi if r == 0 else pi * pos_sf(family, P, np.full_like(y, r))
    else:
        lam = P["lam"]
        dens = np.where(pos, -cpg_logpdf_pos(P, np.where(pos, y, 1.0)), lam)
        cdf_hi, sf_hi = cpg_cdf(P, hi)
        cdf_lo, sf_lo = cpg_cdf(P, np.maximum(lo, 1e-300))
        lat = np.where(k == 0, cdf_hi, np.where(sf_lo < 0.5, sf_lo - sf_hi, cdf_hi - cdf_lo))
        F_hi, F_lo = cdf_hi, np.where(k == 0, 0.0, cdf_lo)
        crps = cpg_crps(P, y)
        for r in thresholds:
            out[f"p_gt_{r:g}"] = -np.expm1(-lam) if r == 0 else cpg_cdf(P, np.full_like(y, r))[1]
    out["nll_density"] = dens
    out["nll_lattice"] = -np.log(np.maximum(lat, 1e-300))
    out["crps"] = crps
    out["F_lo"], out["F_hi"] = F_lo, F_hi  # CDF at the observed lattice bin's edges (for randomised PIT)
    return out
