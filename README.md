# DSA5208 Project 1: Cassandra consistency experiments

The final submission uses **316 completed cases**, covering all 36 combinations
of four properties, three consistency levels and three scenarios. Each cell has
eight or nine cases: **172 PASS, 38 VIOLATION, 106 INCONCLUSIVE**.
The original 1,080-case target was interrupted and was not completed.
All completed outcomes, including three prediction exceptions, are retained.

- Report: `output/pdf/DSA5208_Experiment_Report_316.pdf` (or `report.pdf` in the ZIP).
- Editable Overleaf source: `docs/latex/main.tex`.
- Evidence: `results/final-316-20260924/`.
- Chinese explanation: `docs/assignment_review_zh.md`.
- Teammate update: `docs/change_review_zh.md`.

## Inspect the saved evidence (no database needed)

From the project root, with Python 3.11+:

```bash
python3 scripts/summarize_completed.py
```

This uses only the standard library and supplied checker. It verifies archived
hashes, replays all classifications and checks fault, probe and recovery evidence.
It regenerates audit.json and matrix-summary.json in the evidence directory.

Each case has its original history, environment, controls and completion record.
dataset-selection.json records the cutoff and file hashes. provenance/ preserves
both executed source snapshots and their original plans. The historical plans
still contain 1,080 cases; these are provenance, not a completion claim.
excluded-preparation-failures/ preserves interruptions at cases 94 and 317.
Case 94 later completed in phase 2. Neither failed execution ran a workload.

## Run new measurements (optional)

Use a dedicated Docker daemon with four CPU cores and about 8 GB RAM.
On macOS, the recorded environment used a dedicated Colima profile:

```bash
colima start dsa5208 --cpu 4 --memory 8 --disk 25 \
  --vm-type vz --mount "$(pwd):w" --activate=false --ssh-config=false
export DOCKER_CONTEXT=colima-dsa5208
```

From the project root:

```bash
docker compose build cassandra1 runner
docker compose up -d --wait cassandra1 cassandra2 cassandra3
docker compose run --rm --no-deps runner \
  python scripts/reproduce_independent.py --cases 316
```

Use docker-compose if Compose is installed as a standalone command.
--cases 36 runs one full block; 316 reproduces the selected seeded prefix.
New runs use unique keys, keyspaces and output directories. The portable runner
uses the same workload, fault and probe logic, applying phase 2's preparation
policy (up to three attempts) throughout. Phase 1 had no preparation retries.
Exact outcomes and interruptions need not repeat. No new measurements were run
while assembling this submission.

The runner mounts the dedicated Docker socket to control the three lab containers.
Do not run concurrent suites. Unexpected preparation/control failures stop the
suite and preserve records. The original run_real_experiments.py supplies shared
helpers; its standalone batch mode is an earlier design. Use
reproduce_independent.py for the per-case fault cycles described in this report.

## Interpretation

Setup uses ALL; workloads use the recorded ONE, QUORUM or ALL. RYW/MR compare
successful client observations. MW/WFR check a necessary local predecessor-
visibility condition using a separate verified N1 isolation and ONE probe.
These probes do not reconstruct every internal write order or demonstrate a
stale QUORUM client read. PASS is not a general guarantee; INCONCLUSIVE means
required successful evidence is missing.

Cases have separate fault/recovery cycles but share the VM, cluster and recovery
history. Preparation policy changed between phases. The interruption-based
cutoff was chosen afterwards. Do not interpret raw frequencies as independent
estimates of production failure probability.

## Tests and editing

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev,cassandra]'
pytest -q
```

All 28 tests pass. Synthetic trajectories are checker fixtures, not real results.
Upload the contents of docs/latex/ to Overleaf and compile main.tex with XeLaTeX.

## Stop the dedicated lab

```bash
docker compose stop
colima stop dsa5208  # only for the optional dedicated profile
```

Stopping retains data. The recorded lab was shut down when collection ended.
