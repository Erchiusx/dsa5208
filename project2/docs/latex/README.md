# Report source

`main.tex` is the DSA5208 Project 2 report by Jia Siqi and Jia Zeyue. Jia Zeyue's student
ID is still to be added to the `\memberB` macro at the top before submitting.

## Local compilation

From `project2/`, with Tectonic installed:

```bash
tectonic -X compile docs/latex/main.tex --outdir output/pdf
mv output/pdf/main.pdf output/pdf/DSA5208_Project2_Report.pdf
```

The figures are read from `reports/figures/` through `\graphicspath`.

## Overleaf

Upload this directory together with the PNG files of `reports/figures/` placed in a
`figures/` folder next to `main.tex` (the second `\graphicspath` entry). Select
**XeLaTeX** as the compiler.

## Template attribution

The report uses ElegantPaper, English mode, version 0.12 (2026-02-27), distributed under
the LaTeX Project Public License 1.3c or later; see `LICENSE-ElegantPaper` and
`template-provenance.json`.
