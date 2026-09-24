# Selected final evidence: 316 completed cases

All completed cases in original planned positions 1–316 are retained.
Totals: 172 PASS, 38 VIOLATION, 106 INCONCLUSIVE.
All 36 cells are covered: 28 cells have nine cases, eight have eight.
No pilot/batch histories are added and no unexpected completed outcome is removed.

- cases/: original history, controls, environment and completion for each case.
- dataset-selection.json: selection rule, cutoff, provenance and original file hashes.
- case-summaries.json: selected per-case metadata.
- audit.json: offline verification and aggregate counts.
- matrix-summary.json: 36-cell counts.
- provenance/phase1 and phase2: actually executed source snapshots and original metadata.
- excluded-preparation-failures/: failed executions at planned cases 94 and 317;
  neither ran a formal workload. Case 94 later completed in phase 2.

The original plan targeted 1,080; that target was not completed. Collection stopped
after the second interruption by group decision. Phase 1 has 93 completed cases;
phase 2 has 223 and a changed preparation retry policy. Data share the same cluster
and should not be treated as independent samples of production violation rates.
MW/WFR classifications apply to the local predecessor-visibility probe.

Run python3 scripts/summarize_completed.py from the project root to replay and
verify. Archived source-hashes paths refer to their original local run layout;
the verifier resolves their source/ suffix inside each archived phase.
All original evidence is retained byte for byte. Paths in original manifests
may reference the former local directory; the selection manifest and packaged
case paths locate the final copies.
