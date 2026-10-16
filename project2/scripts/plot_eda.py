#!/usr/bin/env python3
"""Task 1 figures and headline numbers from the Spark summary tables in reports/eda/.

Monthly station totals are rate-based: the rain per observed five-minute reading, times the number
of slots in the month. That is unbiased when readings are missing independently of rain, which holds
for the 2018 outages (a reading after a missing slot carries no extra rain).
- Station-months observed for under half their slots are dropped.
- Island-wide series average a fixed panel of stations that report at least 70 % of every year, so
  changes in the network do not appear as changes in the weather.
- A month without any usable panel station (Aug 2018) is filled with its 2017-2024 mean and drawn
  hatched.
- Station maps use every station, as the ratio of its totals to the island mean over the same months.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import optimize, stats  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parents[1]
YEARS = list(range(2017, 2025))
MONTHS = list("JFMAMJJASOND")
SEASON_OF = {12: "NEM", 1: "NEM", 2: "NEM", 3: "NEM", 4: "IM1", 5: "IM1",
             6: "SWM", 7: "SWM", 8: "SWM", 9: "SWM", 10: "IM2", 11: "IM2"}
SEASONS = {"NEM": "NE monsoon (Dec–Mar)", "IM1": "Inter-monsoon (Apr–May)",
           "SWM": "SW monsoon (Jun–Sep)", "IM2": "Inter-monsoon (Oct–Nov)"}
COLORS = {"NEM": "#1f77b4", "IM1": "#ff7f0e", "SWM": "#2ca02c", "IM2": "#9467bd"}
DUR_LABELS = ["≤ 15 min", "15–60 min", "1–3 h", "3–6 h", "> 6 h"]
LAST30_LABELS = ["dry", "(0, 1] mm", "(1, 5] mm", "> 5 mm"]
MIN_MONTH_COVERAGE = 0.5
PANEL_COVERAGE = 0.7


def days_in_year(y: int) -> int:
    return 366 if y % 4 == 0 else 365


def load(eda: Path) -> dict:
    sm = pd.read_csv(eda / "station_month.csv")
    sm["expected"] = pd.to_datetime(dict(year=sm.year, month=sm.month, day=1)).dt.days_in_month * 288
    sm["coverage"] = sm.slots / sm.expected
    sm["total"] = sm.rain / sm.slots * sm.expected
    sm = sm[sm.coverage >= MIN_MONTH_COVERAGE].copy()
    cov = pd.read_csv(eda / "coverage.csv")
    cov["frac"] = cov.slots / (cov.year.map(days_in_year) * 288)
    frac = cov.pivot(index="station_id", columns="year", values="frac").reindex(columns=YEARS).fillna(0.0)
    panel = sorted(frac.index[(frac >= PANEL_COVERAGE).all(axis=1)])
    grid = pd.MultiIndex.from_product([YEARS, range(1, 13)], names=["year", "month"])
    p = sm[sm.station_id.isin(panel)]
    island = (p.groupby(["year", "month"])
              .agg(total=("total", "mean"), stations=("station_id", "size"), rain=("rain", "sum"),
                   slots=("slots", "sum"), wet=("wet_slots", "sum"))
              .reindex(grid))
    clim = island.total.groupby(level="month").mean()
    island["imputed"] = island.total.isna()
    island["total_filled"] = island.total.fillna(pd.Series(island.index.get_level_values("month").map(clim), index=island.index))
    geo_path = PROJECT_DIR / "data" / "metadata" / "planning_area_boundary_2019.geojson"  # data.gov.sg, optional
    geo = json.loads(geo_path.read_text()) if geo_path.exists() else None
    return dict(sm=sm, frac=frac, panel=panel, island=island, clim=clim, eda=eda, geo=geo)


def season_shading(ax, ymax=None):
    for lo, hi, s in [(0.5, 3.5, "NEM"), (3.5, 5.5, "IM1"), (5.5, 9.5, "SWM"), (9.5, 11.5, "IM2"), (11.5, 12.5, "NEM")]:
        ax.axvspan(lo, hi, color=COLORS[s], alpha=0.08, lw=0)


def fig_coverage(d, out):
    frac, sm = d["frac"], d["sm"]
    raw = pd.read_csv(d["eda"] / "station_month.csv")
    raw["coverage"] = raw.slots / (pd.to_datetime(dict(year=raw.year, month=raw.month, day=1)).dt.days_in_month * 288)
    med = raw.groupby(["year", "month"]).coverage.median().unstack().reindex(index=YEARS, columns=range(1, 13))
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.6), gridspec_kw=dict(width_ratios=[1, 1.4]))
    x = np.arange(len(YEARS))
    ax[0].bar(x - 0.2, (frac > 0).sum().values, 0.4, label="any readings", color="#bbbbbb")
    ax[0].bar(x + 0.2, (frac >= PANEL_COVERAGE).sum().values, 0.4, label=f"≥ {PANEL_COVERAGE:.0%} of the year", color="#4c72b0")
    ax[0].axhline(len(d["panel"]), color="k", ls="--", lw=1,
                  label=f"panel: {len(d['panel'])} stations ≥ {PANEL_COVERAGE:.0%} in every year")
    ax[0].set_ylim(0, 105)
    ax[0].set_xticks(x, YEARS, rotation=45); ax[0].set_ylabel("stations"); ax[0].legend(fontsize=7, loc="upper left", ncol=2)
    ax[0].set_title("(a) Stations reporting", fontsize=10)
    im = ax[1].imshow(med.values, cmap="viridis", vmin=0, vmax=1, aspect="auto")
    for (i, j), v in np.ndenumerate(med.values):
        if v < 0.9:
            ax[1].text(j, i, f"{v:.0%}", ha="center", va="center", fontsize=7, color="w" if v < 0.5 else "k")
    ax[1].set_xticks(range(12), MONTHS); ax[1].set_yticks(range(len(YEARS)), YEARS)
    ax[1].set_title("(b) Median share of five-minute slots observed per station", fontsize=10)
    fig.colorbar(im, ax=ax[1], fraction=0.04)
    fig.tight_layout(); fig.savefig(out / "fig1_coverage.png", dpi=200); plt.close(fig)


def fig_annual_cycle(d, out):
    isl = d["island"].copy()
    isl["wet_frac"] = isl.wet / isl.slots * 100
    isl["intensity"] = isl.rain / isl.wet * 12  # mm/h while raining
    m = np.arange(1, 13)
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.8))
    for a, col, title, ylab in [(ax[0], "total", "(a) Monthly rainfall", "mm per month"),
                                (ax[1], "wet_frac", "(b) Rain frequency", "% of 5-min readings with rain"),
                                (ax[2], "intensity", "(c) Rain intensity when raining", "mm/h (rain per wet 5 min × 12)")]:
        season_shading(a)
        tab = isl[col].unstack("year")
        if col == "total":
            a.bar(m, tab.mean(axis=1), color="#4c72b0", alpha=0.6, label="2017–2024 mean")
        else:
            a.plot(m, tab.mean(axis=1), color="k", lw=2, label="2017–2024 mean")
        for y in YEARS:
            a.scatter(m + (y - 2020.5) * 0.06, tab[y], s=9, color=plt.cm.plasma((y - 2017) / 8), zorder=3,
                      label=str(y) if col == "total" else None)
        a.set_xticks(m, MONTHS); a.set_title(title, fontsize=10); a.set_ylabel(ylab)
    top = ax[1].get_ylim()[1] * 1.12
    ax[1].set_ylim(top=top)
    for s, x in [("NEM", 2), ("IM1", 4.5), ("SWM", 7.5), ("IM2", 10.5)]:
        ax[1].text(x, top * 0.985, s, ha="center", va="top", fontsize=8, color=COLORS[s])
    fig.legend(*ax[0].get_legend_handles_labels(), loc="lower center", ncol=9, fontsize=8, frameon=False)
    fig.tight_layout(rect=(0, 0.07, 1, 1)); fig.savefig(out / "fig2_annual_cycle.png", dpi=200); plt.close(fig)


def fig_diurnal(d, out):
    di = pd.read_csv(d["eda"] / "diurnal.csv")
    by = di.groupby(["hod", "month"])[["rain", "slots"]].sum()
    rate = (by.rain / by.slots * 12).unstack("month")
    di["season"] = di.month.map(SEASON_OF)
    s = di.groupby(["season", "hod"])[["rain", "slots", "wet_hours", "hours"]].sum()
    fig, ax = plt.subplots(1, 3, figsize=(14, 4.2), gridspec_kw=dict(width_ratios=[1.2, 1, 1]))
    im = ax[0].imshow(rate.values, origin="lower", aspect="auto", cmap="Blues")
    ax[0].set_xticks(range(12), MONTHS); ax[0].set_yticks(range(0, 24, 3), [f"{h:02d}:00" for h in range(0, 24, 3)])
    ax[0].set_ylabel("hour starting (SGT)"); ax[0].set_title("(a) Mean rain rate (mm/h), 2017–2024", fontsize=10)
    fig.colorbar(im, ax=ax[0], fraction=0.05)
    for k in SEASONS:
        x = s.loc[k]
        ax[1].plot(x.index, x.rain / x.slots * 12, color=COLORS[k], lw=2, label=SEASONS[k])
        ax[2].plot(x.index, x.wet_hours / x.hours * 100, color=COLORS[k], lw=2, label=SEASONS[k])
    ax[1].set_title("(b) Mean rain rate by season", fontsize=10); ax[1].set_ylabel("mm/h")
    ax[2].set_title("(c) Share of hours with rain", fontsize=10); ax[2].set_ylabel("% of complete station-hours")
    for a in ax[1:]:
        a.set_xticks(range(0, 24, 3), [f"{h:02d}" for h in range(0, 24, 3)]); a.set_xlabel("hour starting (SGT)"); a.grid(alpha=0.3)
    ax[1].legend(fontsize=8)
    fig.tight_layout(); fig.savefig(out / "fig3_diurnal.png", dpi=200); plt.close(fig)
    return {k: {"peak_hour_rate": int((s.loc[k].rain / s.loc[k].slots).idxmax()),
                "rate_peak_over_mean": float((s.loc[k].rain / s.loc[k].slots).max() / (s.loc[k].rain.sum() / s.loc[k].slots.sum()))}
            for k in SEASONS}


def station_index(d):
    """Station total over the island (panel) mean of the same year-months, overall and per season."""
    sm, isl = d["sm"].copy(), d["island"]
    sm = sm.join(isl.total.rename("island"), on=["year", "month"]).dropna(subset=["island"])
    sm["season"] = sm.month.map(SEASON_OF)
    st = pd.read_csv(d["eda"] / "stations.csv").set_index("station_id")
    out = {}
    g = sm.groupby("station_id")
    out["all"] = (g.total.sum() / g.island.sum()).where(g.size() >= 12)
    for k in SEASONS:
        h = sm[sm.season == k].groupby("station_id")
        out[k] = (h.total.sum() / h.island.sum()).where(h.size() >= 4)
    return st.join(pd.DataFrame(out), how="inner")


def draw_land(ax, geo):
    for f in (geo or {}).get("features", []):
        g = f["geometry"]
        for poly in [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]:
            ring = np.asarray(poly[0])[:, :2]
            ax.fill(ring[:, 0], ring[:, 1], facecolor="#f0f0f0", edgecolor="#c8c8c8", lw=0.3, zorder=0)


def fig_maps(d, out):
    idx = station_index(d)
    annual = d["island"].groupby(level="year").total_filled.sum().mean()
    fig = plt.figure(figsize=(14, 6.2))
    gs = fig.add_gridspec(2, 3, width_ratios=[1.6, 1, 1], wspace=0.08, hspace=0.18)
    a = fig.add_subplot(gs[:, 0])
    x = idx.dropna(subset=["all"])
    draw_land(a, d.get("geo"))
    sc = a.scatter(x.lon, x.lat, c=x["all"] * annual, cmap="YlGnBu", s=55, edgecolor="k", lw=0.4)
    fig.colorbar(sc, ax=a, orientation="horizontal", fraction=0.05, pad=0.06, aspect=40, label="mm / year (2017–2024)")
    a.set_title(f"(a) Mean annual rainfall, {len(x)} stations", fontsize=10)
    axes = [a]
    for i, k in enumerate(SEASONS):
        b = fig.add_subplot(gs[i // 2, 1 + i % 2])
        x = idx.dropna(subset=[k])
        draw_land(b, d.get("geo"))
        sc = b.scatter(x.lon, x.lat, c=(x[k] - 1) * 100, cmap="BrBG", vmin=-30, vmax=30, s=28, edgecolor="k", lw=0.3)
        b.set_title(f"({'bcde'[i]}) {SEASONS[k]}", fontsize=9)
        b.set_xticks([]); b.set_yticks([])
        axes.append(b)
    fig.colorbar(sc, ax=axes[1:], fraction=0.03, pad=0.02, label="% above / below the island mean")
    for b in axes:
        b.set_aspect("equal"); b.set_xlim(103.6, 104.05); b.set_ylim(1.2, 1.48); b.tick_params(labelsize=7)
        for side in ("top", "right", "bottom", "left"):
            b.spines[side].set_visible(b is axes[0] and side in ("bottom", "left"))
    fig.savefig(out / "fig4_spatial.png", dpi=200, bbox_inches="tight"); plt.close(fig)
    # east-west contrast per season: correlation of the station index with longitude
    res = {"annual_mm_range": [float(idx["all"].min() * annual), float(idx["all"].max() * annual)], "stations": int(idx["all"].notna().sum())}
    for k in ["all", *SEASONS]:
        x = idx.dropna(subset=[k])
        res[f"lon_corr_{k}"] = float(stats.spearmanr(x.lon, x[k]).statistic)
        res[f"lat_corr_{k}"] = float(stats.spearmanr(x.lat, x[k]).statistic)
    return res


def fig_interannual(d, out):
    isl = d["island"]
    annual = isl.groupby(level="year").total_filled.sum()
    imputed = isl.groupby(level="year").imputed.sum()
    # station annual totals: missing months filled with the station's own mean for that month
    sm = d["sm"][d["sm"].station_id.isin(d["panel"])]
    st_clim = sm.groupby(["station_id", "month"]).total.mean()
    full = pd.MultiIndex.from_product([d["panel"], YEARS, range(1, 13)], names=["station_id", "year", "month"])
    t = sm.set_index(["station_id", "year", "month"]).total.reindex(full)
    filled = t.fillna(pd.Series(st_clim.reindex(pd.MultiIndex.from_arrays([full.get_level_values(0), full.get_level_values(2)])).values, index=full))
    st_annual = filled.groupby(level=["station_id", "year"]).sum().unstack("year")
    anom = (isl.total.unstack("month") / d["clim"].values - 1) * 100
    fig, ax = plt.subplots(1, 2, figsize=(14, 4.2), gridspec_kw=dict(width_ratios=[1, 1.5]))
    x = np.arange(len(YEARS))
    bars = ax[0].bar(x, annual.values, color="#4c72b0", alpha=0.7)
    for b, n in zip(bars, imputed.values):
        if n:
            b.set_hatch("//"); b.set_alpha(0.45)
    ax[0].boxplot([st_annual[y].values for y in YEARS], positions=x, widths=0.35, showfliers=True,
                  flierprops=dict(markersize=3), medianprops=dict(color="k"))
    ax[0].axhline(annual.mean(), color="k", ls="--", lw=1)
    ax[0].set_xticks(x, YEARS); ax[0].set_ylabel("mm"); ax[0].set_title(
        f"(a) Annual rainfall: island mean (bars) and {len(d['panel'])} panel stations (boxes)", fontsize=10)
    im = ax[1].imshow(anom.values, cmap="BrBG", vmin=-100, vmax=100, aspect="auto")
    tot = isl.total.unstack("month")
    for (i, j), v in np.ndenumerate(tot.values):
        ax[1].text(j, i, "n/a" if np.isnan(v) else f"{v:.0f}", ha="center", va="center", fontsize=7)
    ax[1].set_xticks(range(12), MONTHS); ax[1].set_yticks(range(len(YEARS)), YEARS)
    ax[1].set_title("(b) Monthly rainfall (mm, numbers) and anomaly vs 2017–2024 mean (colour, %)", fontsize=10)
    fig.colorbar(im, ax=ax[1], fraction=0.03, label="%")
    fig.tight_layout(); fig.savefig(out / "fig5_interannual.png", dpi=200); plt.close(fig)
    return annual, imputed, anom, st_annual


def fig_freq_extremes(d, out):
    isl = d["island"]
    y = isl.groupby(level="year")[["rain", "wet", "slots"]].sum()
    y["wet_frac"] = y.wet / y.slots * 100
    y["intensity"] = y.rain / y.wet * 12
    ex = pd.read_csv(d["eda"] / "extremes.csv")
    ex = ex[ex.station_id.isin(d["panel"])].merge(
        d["frac"].stack().rename("frac").reset_index(), on=["station_id", "year"])
    ex["gt20_rate"] = ex.hours_gt20 / ex.frac  # per fully observed year
    fig, ax = plt.subplots(1, 3, figsize=(14, 3.8))
    xs = np.arange(len(YEARS))
    total = isl.groupby(level="year").total_filled.sum()
    ax[0].bar(xs, (total / total.mean() - 1).values * 100, color="#bbbbbb", label="annual rainfall")
    ax[0].plot(xs, (y.wet_frac / y.wet_frac.mean() - 1).values * 100, "o-", color="#4c72b0", label="frequency (share of wet readings)")
    ax[0].plot(xs, (y.intensity / y.intensity.mean() - 1).values * 100, "s--", color="#c44e52", label="intensity (rain per wet reading)")
    ax[0].axhline(0, color="k", lw=0.8); ax[0].set_ylabel("% vs 2017–2024 mean"); ax[0].legend(fontsize=7, loc="lower right")
    ax[0].set_title("(a) Annual rainfall = frequency × intensity", fontsize=10)
    ax[1].boxplot([ex[ex.year == yr].max_hour.values for yr in YEARS], positions=xs, widths=0.5,
                  flierprops=dict(markersize=3), medianprops=dict(color="k"))
    ax[1].set_ylabel("mm in one hour"); ax[1].set_title("(b) Annual maximum hourly rainfall per station", fontsize=10)
    m = ex.groupby("year").gt20_rate.mean()
    ax[2].bar(xs, m.values, color="#8172b2")
    ax[2].set_ylabel("hours per station-year"); ax[2].set_title("(c) Hours with > 20 mm per station", fontsize=10)
    for a in ax:
        a.set_xticks(xs, YEARS, rotation=45)
    fig.tight_layout(); fig.savefig(out / "fig6_frequency_extremes.png", dpi=200); plt.close(fig)
    return y, ex


def fig_events(d, out):
    eb = pd.read_csv(d["eda"] / "events_by_month.csv")
    m = eb.groupby(["month", "dur_class"]).rain.sum().unstack("dur_class").reindex(columns=range(5)).fillna(0)
    share = m.div(m.sum(axis=1), axis=0) * 100
    ec = pd.read_csv(d["eda"] / "events_by_class.csv")
    fig, ax = plt.subplots(1, 3, figsize=(14, 3.8))
    bottom = np.zeros(12)
    cols = plt.cm.viridis(np.linspace(0.1, 0.9, 5))
    for k in range(5):
        ax[0].bar(range(1, 13), share[k].values, bottom=bottom, color=cols[k], label=DUR_LABELS[k])
        bottom += share[k].values
    ax[0].set_xticks(range(1, 13), MONTHS); ax[0].set_ylabel("% of rain"); ax[0].set_ylim(0, 118)
    ax[0].legend(fontsize=7, title="event duration", title_fontsize=7, ncol=5, loc="upper center", handlelength=1, columnspacing=0.6)
    ax[0].set_title("(a) Rain by event duration", fontsize=10)
    for k in SEASONS:
        x = ec[ec.season == k].groupby("hod_start").rain.sum().reindex(range(24), fill_value=0)
        ax[1].plot(x.index, x / x.sum() * 100, color=COLORS[k], lw=2, label=SEASONS[k])
    ax[1].set_xticks(range(0, 24, 3), [f"{h:02d}" for h in range(0, 24, 3)]); ax[1].set_xlabel("event start (SGT)")
    ax[1].set_ylabel("% of season's rain"); ax[1].set_title("(b) When rain events start (rain-weighted)", fontsize=10)
    ax[1].legend(fontsize=7); ax[1].grid(alpha=0.3)
    s = ec.groupby("season")[["events", "rain", "minutes", "sum_peak5"]].sum()
    s["depth"] = s.rain / s.events; s["dur"] = s.minutes / s.events; s["peak"] = s.sum_peak5 / s.events * 12
    xs = np.arange(len(SEASONS))
    order = list(SEASONS)
    ax[2].bar(xs, s.loc[order, "peak"], 0.6, color=[COLORS[k] for k in order])
    for i, k in enumerate(order):
        ax[2].text(i, s.loc[k, "peak"] + 0.3, f"{s.loc[k, 'depth']:.1f} mm\n{s.loc[k, 'dur']:.0f} min", ha="center", fontsize=7)
    ax[2].set_xticks(xs, order); ax[2].set_ylabel("mean peak 5-min intensity (mm/h)"); ax[2].set_ylim(0, s.peak.max() * 1.25)
    ax[2].set_title("(c) Mean event peak intensity, depth, duration", fontsize=10)
    fig.tight_layout(); fig.savefig(out / "fig7_events.png", dpi=200); plt.close(fig)
    return share, s


def fig_correlation(d, out):
    pc = pd.read_csv(d["eda"] / "pair_correlation.csv").dropna(subset=["corr"])
    pc = pc[pc.n >= np.where(pc.scale == "hour", 2000, 100)]
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.8), sharey=True)
    fits = {}
    bins = np.arange(0, 52.5, 2.5)
    for a, scale in zip(ax, ["hour", "day"]):
        for k in SEASONS:
            x = pc[(pc.scale == scale) & (pc.season == k)]
            a.scatter(x.dist_km, x["corr"], s=2, color=COLORS[k], alpha=0.12)
            b = x.groupby(pd.cut(x.dist_km, bins))["corr"].mean()
            (c0, length), _ = optimize.curve_fit(lambda r, c0, L: c0 * np.exp(-r / L), x.dist_km, x["corr"], p0=(0.9, 20),
                                                 bounds=([0, 0.1], [1, 1000]))
            fits[f"{scale}_{k}"] = {"c0": float(c0), "efold_km": float(length), "pairs": int(len(x))}
            a.plot([iv.mid for iv in b.index], b.values, color=COLORS[k], lw=2, label=f"{SEASONS[k]}: e-folding {length:.0f} km")
        a.set_xlabel("distance between stations (km)")
        a.set_title(f"({'ab'[scale == 'day']}) {'hourly' if scale == 'hour' else 'daily'} totals", fontsize=10)
        a.grid(alpha=0.3); a.set_ylim(-0.05, 1); a.legend(fontsize=7)
    ax[0].set_ylabel("Pearson correlation")
    fig.tight_layout(); fig.savefig(out / "fig8_spatial_correlation.png", dpi=200); plt.close(fig)
    return fits


def fig_persistence(d, out):
    pe = pd.read_csv(d["eda"] / "persistence.csv")
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.8))
    by = pe.groupby(["last30_class", "hod"])[["rows", "gt1"]].sum()
    cols = plt.cm.cividis(np.linspace(0.05, 0.85, 4))
    for c in range(4):
        x = by.loc[c]
        ax[0].plot(x.index, x.gt1 / x.rows, color=cols[c], lw=2, label=f"last 30 min {LAST30_LABELS[c]}")
    ax[0].set_yscale("log"); ax[0].set_xticks(range(0, 24, 3), [f"{h:02d}" for h in range(0, 24, 3)])
    ax[0].set_xlabel("prediction hour (SGT)"); ax[0].set_ylabel("P(next 30 min > 1 mm)"); ax[0].legend(fontsize=7)
    ax[0].set_title("(a) Persistence and the diurnal cycle", fontsize=10); ax[0].grid(alpha=0.3, which="both")
    tot = pe.groupby("last30_class")[["rows", "gt0.2", "gt1", "gt5", "gt10"]].sum()
    r = ["gt0.2", "gt1", "gt5", "gt10"]
    xs = np.arange(4)
    for c in range(4):
        ax[1].bar(xs + (c - 1.5) * 0.2, tot.loc[c, r] / tot.loc[c, "rows"], 0.2, color=cols[c], label=LAST30_LABELS[c])
    allp = tot[r].sum() / tot.rows.sum()
    ax[1].scatter(xs, allp, marker="_", s=400, color="r", zorder=3, label="all rows")
    ax[1].set_yscale("log"); ax[1].set_xticks(xs, ["> 0.2 mm", "> 1 mm", "> 5 mm", "> 10 mm"])
    ax[1].set_ylim(1e-3, 8); ax[1].set_ylabel("probability (next 30 min)")
    ax[1].legend(fontsize=7, title="last 30 min", title_fontsize=7, ncol=5, loc="upper center", handlelength=1, columnspacing=0.6)
    ax[1].set_title("(b) Exceedance probability given the last 30 min", fontsize=10)
    fig.tight_layout(); fig.savefig(out / "fig9_persistence.png", dpi=200); plt.close(fig)
    return {f"P_gt{k[2:]}_given_{LAST30_LABELS[c]}": float(tot.loc[c, k] / tot.loc[c, "rows"]) for c in range(4) for k in r} | \
           {f"P_gt{k[2:]}_all": float(allp[k]) for k in r} | {f"rows_{LAST30_LABELS[c]}": int(tot.loc[c, "rows"]) for c in range(4)}


def kendall(series: pd.Series) -> dict:
    t = stats.kendalltau(series.index, series.values)
    slope = stats.theilslopes(series.values, series.index)
    return {"tau": float(t.statistic), "p": float(t.pvalue), "sen_slope_per_year": float(slope.slope)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eda-dir", type=Path, default=PROJECT_DIR / "reports" / "eda")
    parser.add_argument("--out-dir", type=Path, default=PROJECT_DIR / "reports" / "figures")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    d = load(args.eda_dir)
    summary = {"panel_stations": d["panel"], "months_imputed": [f"{y}-{m:02d}" for (y, m), v in d["island"].imputed.items() if v]}
    fig_coverage(d, args.out_dir)
    fig_annual_cycle(d, args.out_dir)
    isl = d["island"]
    clim = d["clim"]
    summary["monthly_climatology_mm"] = {MONTHS[m - 1] + str(m): round(float(v), 1) for m, v in clim.items()}
    mc = isl.groupby(level="month")[["rain", "wet", "slots"]].sum()
    summary["wet_frac_by_month_pct"] = (mc.wet / mc.slots * 100).round(2).tolist()
    summary["intensity_by_month_mmh"] = (mc.rain / mc.wet * 12).round(2).tolist()
    summary["diurnal"] = fig_diurnal(d, args.out_dir)
    summary["spatial"] = fig_maps(d, args.out_dir)
    annual, imputed, anom, st_annual = fig_interannual(d, args.out_dir)
    summary["annual_mm"] = {int(y): round(float(v), 1) for y, v in annual.items()}
    summary["annual_months_imputed"] = {int(y): int(v) for y, v in imputed.items()}
    summary["annual_station_cv"] = {int(y): round(float(st_annual[y].std() / st_annual[y].mean()), 3) for y in YEARS}
    extremes = anom.stack().dropna().sort_values().iloc[[0, 1, 2, -3, -2, -1]]
    summary["largest_monthly_anomalies_pct"] = {f"{y}-{m:02d}": round(float(v)) for (y, m), v in extremes.items()}
    yr, ex = fig_freq_extremes(d, args.out_dir)
    summary["wet_frac_by_year_pct"] = yr.wet_frac.round(3).to_dict()
    summary["intensity_by_year_mmh"] = yr.intensity.round(3).to_dict()
    summary["trend_tests"] = {"annual_total": kendall(annual), "wet_frac": kendall(yr.wet_frac), "intensity": kendall(yr.intensity),
                              "median_max_hour": kendall(ex.groupby("year").max_hour.median()),
                              "hours_gt20_rate": kendall(ex.groupby("year").gt20_rate.mean())}
    summary["annual_vs_frequency_corr"] = float(np.corrcoef(annual.values, yr.wet_frac.values)[0, 1])
    summary["annual_vs_intensity_corr"] = float(np.corrcoef(annual.values, yr.intensity.values)[0, 1])
    share, ev = fig_events(d, args.out_dir)
    summary["events_rain_share_pct_by_month"] = share.round(1).to_dict(orient="index")
    summary["events_by_season"] = ev[["events", "depth", "dur", "peak"]].round(2).to_dict(orient="index")
    summary["correlation_fits"] = fig_correlation(d, args.out_dir)
    summary["persistence"] = fig_persistence(d, args.out_dir)
    (args.eda_dir / "summary.json").write_text(json.dumps(summary, indent=1, default=float) + "\n")
    print(json.dumps(summary, indent=1, default=float))


if __name__ == "__main__":
    main()
