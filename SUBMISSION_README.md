# Submission contents

Final scope: 316 completed Cassandra cases, all 36 combinations, eight or nine
cases per cell. Totals: 172 PASS, 38 VIOLATION, 106 INCONCLUSIVE.

The submission ZIP has one PDF, report.pdf; source code and Docker files;
editable Overleaf source under docs/latex; tests and synthetic checker fixtures;
and results/final-316-20260924 with per-case evidence and execution provenance.

From the extracted project root, run:
    python3 scripts/summarize_completed.py

This verifies the saved data without running Cassandra. Follow README.md only
if new measurements are desired. Original plans still show the 1,080-case target,
which was not completed. The PDF explains the cutoff, preparation policy changes,
unexpected results, and limits of MW/WFR local probes. No unexecuted second-resume
recovery changes are included. The archive contains no Git metadata or credentials.
