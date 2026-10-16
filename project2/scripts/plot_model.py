#!/usr/bin/env python3
"""Task 2 report figures from the evaluation reports and reports/final_model/*.csv.

fig10_model_skill.png : Brier skill of ZILN and the final model by threshold (QC'd 2024), and
                        the final model's reliability diagram.
fig11_skill_by_condition.png : skill of the final model by SGT hour and season, and the share of
                        events and of Brier score by the recent-rain state.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parents[1]
REPORTS = PROJECT_DIR / "reports"
FIG_DIR = REPORTS / "figures"
SEASONS = ["NEM", "IM1", "SWM", "IM2"]
SEASON_NAMES = {"NEM": "NE monsoon (Dec–Mar)", "IM1": "Inter-monsoon (Apr–May)",
                "SWM": "SW monsoon (Jun–Sep)", "IM2": "Inter-monsoon (Oct–Nov)"}
SEASON_COLORS = {"NEM": "tab:blue", "IM1": "tab:orange", "SWM": "tab:green", "IM2": "tab:purple"}
STATES = ["station wet", "neighbour wet", "all dry"]
STATE_LABELS = {"station wet": "station wet in last 60 min", "neighbour wet": "only a neighbour wet",
                "all dry": "station and 8 neighbours dry"}


def style(ax) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(alpha=0.3, lw=0.6)


def fig_skill() -> None:
    ev = json.loads((REPORTS / "amount_models_qc_evaluation.json").read_text())["models"]
    boot = json.loads((REPORTS / "amount_bootstrap_mlp_qc_vs_ziln_qc.json").read_text())["brier_skill_gain"]
    th = list(ev["mlp_qc"]["thresholds"])
    x = np.arange(len(th))
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.9), gridspec_kw={"width_ratios": [1, 1.05]})
    ax = axes[0]
    for name, label, color, marker in (("ziln", "ZILN", "0.5", "s"), ("mlp_qc", "final (GBT occurrence + MLP amount)", "tab:blue", "o")):
        ax.plot(x, [ev[name]["thresholds"][t]["brier_skill_score"] for t in th], marker=marker, color=color, label=label)
    for i, t in enumerate(th):
        ax.annotate(f"+{boot[t]['diff']:.3f}", (i, ev["mlp_qc"]["thresholds"][t]["brier_skill_score"]),
                    textcoords="offset points", xytext=(0, 7), ha="center", fontsize=7.5, color="tab:blue")
    ax.set_xticks(x, [f"> {t}" for t in th])
    ax.set_xlabel("threshold r (mm in the next 30 min)")
    ax.set_ylabel("Brier skill score vs climatology")
    ax.set_ylim(0, 0.62)
    ax.set_title("(a) Skill by threshold, 2024 (numbers: gain over ZILN)", fontsize=10)
    ax.legend(fontsize=8, loc="lower left", frameon=False)
    style(ax)

    rel = pd.read_csv(REPORTS / "final_model" / "reliability.csv")
    ax = axes[1]
    ax.plot([1e-4, 1], [1e-4, 1], color="0.6", lw=0.8, ls="--")
    for r, color in zip(sorted(rel["r"].unique()), ["tab:green", "tab:blue", "tab:orange", "tab:red"]):
        d = rel[(rel["r"] == r) & (rel["rows"] >= 200)]
        ax.plot(d["mean_p"], d["event_rate"], marker="o", ms=3.5, color=color, label=f"r = {r:g} mm")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(3e-4, 1); ax.set_ylim(3e-4, 1)
    ax.set_xlabel("mean forecast probability in bin")
    ax.set_ylabel("observed frequency")
    ax.set_title("(b) Reliability of the final model, 2024", fontsize=10)
    ax.legend(fontsize=8, loc="upper left", frameon=False)
    style(ax)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig10_model_skill.png", dpi=200)
    plt.close(fig)


def fig_conditions() -> pd.DataFrame:
    st = pd.read_csv(REPORTS / "final_model" / "stratified.csv")
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8), gridspec_kw={"width_ratios": [1.3, 0.85, 1.0]})
    ax = axes[0]
    for r, color in ((1.0, "tab:blue"), (5.0, "tab:orange")):
        d = st[(st["by"] == "hour") & (st["r"] == r)].assign(h=lambda f: f["group"].astype(int)).sort_values("h")
        ax.plot(d["h"], d["bss"], marker="o", ms=3, color=color, label=f"> {r:g} mm")
    ax.set_xticks(range(0, 24, 3), [f"{h:02d}" for h in range(0, 24, 3)])
    ax.set_xlabel("prediction hour (SGT)")
    ax.set_ylabel("Brier skill score")
    ax.set_title("(a) Skill by time of day", fontsize=10)
    ax.legend(fontsize=8, frameon=False)
    style(ax)

    ax = axes[1]
    w = 0.38
    for j, (r, hatch) in enumerate(((1.0, None), (5.0, "//"))):
        d = st[(st["by"] == "season") & (st["r"] == r)].set_index("group").loc[SEASONS]
        ax.bar(np.arange(4) + (j - 0.5) * w, d["bss"], w, color=[SEASON_COLORS[s] for s in SEASONS],
               hatch=hatch, edgecolor="white", label=f"> {r:g} mm")
    ax.set_xticks(range(4), SEASONS)
    ax.set_ylabel("Brier skill score")
    ax.set_title("(b) Skill by season", fontsize=10)
    ax.set_ylim(0, 0.62)
    leg = ax.legend(fontsize=8, frameon=False, loc="upper center", ncol=2)
    for patch in leg.get_patches():
        patch.set_facecolor("0.6")
    style(ax)

    ax = axes[2]
    d = st[(st["by"] == "state") & (st["r"] == 1.0)].set_index("group").loc[STATES]
    shares = pd.DataFrame({"rows": d["rows"] / d["rows"].sum(), "events (> 1 mm)": d["events"] / d["events"].sum(),
                           "Brier score": d["brier_sum"] / d["brier_sum"].sum()})
    left = np.zeros(3)
    colors = ["#2b6ca3", "#8fb3d9", "#d9d9d9"]
    for state, color in zip(STATES, colors):
        v = shares.loc[state].to_numpy()
        ax.barh(range(3), v, left=left, color=color, edgecolor="white", label=STATE_LABELS[state])
        for k in range(3):
            if v[k] > 0.06:
                ax.text(left[k] + v[k] / 2, k, f"{100 * v[k]:.0f}%", ha="center", va="center", fontsize=8)
        left += v
    ax.set_yticks(range(3), shares.columns)
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xlabel("share of 2024 total, r = 1 mm")
    ax.set_title("(c) Where events and errors come from", fontsize=10)
    ax.legend(fontsize=7.5, frameon=False, loc="upper center", bbox_to_anchor=(0.4, -0.2), ncol=2)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig11_skill_by_condition.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    return st


def main() -> None:
    fig_skill()
    st = fig_conditions()
    out = {}
    for by in ("all", "state", "season"):
        for r in (1.0, 5.0):
            d = st[(st["by"] == by) & (st["r"] == r)]
            for _, row in d.iterrows():
                out[f"{by}:{row['group']}:{r:g}"] = {
                    "rows": int(row["rows"]), "events": int(row["events"]), "bss": round(row["bss"], 4),
                    "mean_p_over_rate": round(row["sum_p"] / row["events"], 3) if row["events"] else None,
                    "share_rows": round(row["rows"] / d["rows"].sum(), 4),
                    "share_events": round(row["events"] / d["events"].sum(), 4),
                    "share_brier": round(row["brier_sum"] / d["brier_sum"].sum(), 4)}
    hours = st[(st["by"] == "hour") & (st["r"] == 1.0)]
    out["hour_bss_1mm_range"] = [round(hours["bss"].min(), 4), round(hours["bss"].max(), 4)]
    (REPORTS / "final_model" / "summary.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
