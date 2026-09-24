# DSA5208 report - ElegantPaper

This directory is a self-contained Overleaf project. Zip the contents of this directory
and upload the ZIP as a new project, select `main.tex`
as the main document, and choose **XeLaTeX** as the compiler. Recompile twice
if cross-reference labels have not settled. No external images are required.

Edit `main.tex` to revise the report. The title block identifies Jia Siqi and Jia Zeyue,
the course and university. The report uses the selected 316 completed cases in `results/final-316-20260924/`.
`main.tex` is the complete editable report; `docs/experiment_report.md` is a short index.

Local compilation from the repository root:

    mkdir -p tmp/pdfs/elegant-build
    tectonic -X compile docs/latex/main.tex --outdir tmp/pdfs/elegant-build

The compiled file is `tmp/pdfs/elegant-build/main.pdf`; the reviewed output is
`output/pdf/DSA5208_Experiment_Report_316.pdf`.

## Template provenance

Template: ElegantPaper, English mode; original class file retained unchanged.
Class version: 0.12, dated 2026-02-27 in the upstream file.

- Overleaf gallery: https://www.overleaf.com/latex/templates/elegantpaper-template/yzghrqjhmmmr
- Author repository: https://github.com/ElegantLaTeX/ElegantPaper
- Downloaded file: https://raw.githubusercontent.com/ElegantLaTeX/ElegantPaper/master/elegantpaper.cls
- Retrieved: 2026-09-23
- License: LaTeX Project Public License 1.3c or later (included).

Report-specific settings in main.tex adjust margins and line spacing, add
three-line tables and shaded shell listings, and use linked reference numbers.
They do not modify the supplied class. The author names were supplied by the group.
