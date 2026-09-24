# Final report: 316 completed cases

The complete editable report is [latex/main.tex](latex/main.tex), using ElegantPaper.
The final PDF is `output/pdf/DSA5208_Experiment_Report_316.pdf`.
Authors: Jia Siqi and Jia Zeyue.

The dataset is `results/final-316-20260924/`: all completed cases in planned
positions 1–316, covering all 36 combinations. There are 172 PASS, 38 VIOLATION
and 106 INCONCLUSIVE histories. Twenty-eight cells have nine cases; eight have eight.
MW/WFR classifications describe local dependency visibility, not a full ordering proof.

The report explains both interruptions, the changed preparation policy, the
three unexpected outcomes, and the limits of the stopping rule and local probes.
It does not claim that 1,080 independent cases completed. Earlier batch and pilot
results are excluded. Run `python3 scripts/summarize_completed.py` to verify the
saved results without launching Cassandra. See the root README for reproduction.
