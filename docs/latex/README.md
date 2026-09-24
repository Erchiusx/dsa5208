# Report source

`main.tex` contains the report by Jia Siqi and Jia Zeyue.

## Overleaf

Upload the contents of this directory as a new Overleaf project. Select
`main.tex` as the main document and **XeLaTeX** as the compiler. Compile twice
if cross-reference labels have not settled. No external images are required.

## Local compilation

From the project root, with Tectonic installed:

```bash
mkdir -p tmp/pdfs/build
tectonic -X compile docs/latex/main.tex --outdir tmp/pdfs/build
```

The compiled file is `tmp/pdfs/build/main.pdf`. The submission PDF is
`output/pdf/DSA5208_Project1_Report.pdf`.

## Template attribution

The report uses ElegantPaper, English mode, version 0.12 (2026-02-27).
The class is distributed under the LaTeX Project Public License 1.3c or later;
see `LICENSE-ElegantPaper`. Retrieval details are in `template-provenance.json`.

- [ElegantPaper repository](https://github.com/ElegantLaTeX/ElegantPaper)
- [Overleaf template](https://www.overleaf.com/latex/templates/elegantpaper-template/yzghrqjhmmmr)
