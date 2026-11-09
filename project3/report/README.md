# Project 3 report

The completed English report is `main.pdf`; editable LaTeX is `main.tex`.
`README.pdf` is a paginated copy of the project root `README.md`.
The named delivery copy is `../output/pdf/DSA5208_Project3_Report.pdf`.
Both PDF copies contain the same 16-page document.

The report introduces game-tree search with a two-ply pruning example and
shows all seven benchmark boards with their exact FEN inputs directly below. The argument
distinguishes original-algorithm acceleration from fixed-task
scaling, measures pruning inflation, compares split-depth and seeded-root
strategies, and uses GPU phase profiling to evaluate a transfer-only explanation. The 9 November
revision is documented in REVISION_AUDIT.md, including changed uncertainty
plots, launcher-inclusive timings and limits on causal interpretation.
All additions are based on existing measured results; no new performance
experiments were run while writing the report.

## Rebuild

From `project3/`, with NumPy, Matplotlib and Tectonic installed:

```sh
python3 report/build_analysis.py
python3 report/build_boards.py
mkdir -p output/pdf
tectonic --keep-logs --outdir output/pdf report/main.tex
cp output/pdf/main.pdf output/pdf/DSA5208_Project3_Report.pdf
cp output/pdf/main.pdf report/main.pdf
python3 report/export_readme.py  # requires reportlab and DejaVu fonts
```

The analysis script regenerates five vector figures and the embedded CPU
result tables from the archived CSV and JSONL records. The board script
regenerates two vector plates directly from the benchmark FEN definitions and
checks them against the appendix. The analysis script edits only its
marked generated-table regions in `main.tex`. Retain `assets/` alongside the
LaTeX source. A normal LaTeX installation can alternatively compile with
`pdflatex` twice from `project3/`.

## Evidence and scope

- Six additional positions: 120 complete three-trial configuration groups,
  including 24 strong-scaling points. Source records are in
  `../experiments/multiposition/`.
- Original initial-position experiments and GPU results: `../experiments/raw/`.
- Original seeded-root imbalance diagnostics: `../experiments/pv/`.
- Three error-bar samples are observed runtime ranges, not confidence intervals.
- The older initial-position one-worker task baseline has one trial. New
  position baselines have three; these limitations are stated separately.
- Ruy Lopez and Queen's Gambit depth-four results are small-workload limitations,
  not evidence about the scalability of those openings generally.
- Node counts, time inflation, allocated core-time and actual energy are not
  interchangeable. Hardware/allocation differences limit causal claims.
- GPU timing includes CPU construction; explicit copies are separately timed,
  while the target-search region still includes launch and synchronization.

The report includes both members' existing names and student IDs, third-party
library attribution, AI-use disclosure and full FEN inputs. Read and understand
the conclusions before submitting. The PDF was rendered and visually reviewed;
the final LaTeX build reported no overfull boxes or unresolved citations.
