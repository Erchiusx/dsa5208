# DSA5208 Project 1: Client-Centric Consistency in Cassandra

Jia Siqi and Jia Zeyue · National University of Singapore

This project investigates read-your-writes, monotonic reads, monotonic writes,
and writes-follow-reads in a three-node Cassandra cluster. It compares ONE,
QUORUM and ALL under normal operation, a stopped node and a network partition.
The dataset contains 316 completed cases across all 36 combinations:
172 PASS, 38 VIOLATION and 106 INCONCLUSIVE.

## Contents

- [Report](output/pdf/DSA5208_Project1_Report.pdf)
- [LaTeX source](docs/latex/main.tex) and [compilation instructions](docs/latex/README.md)
- `src/project1/`: workload execution, fault control and consistency checker
- `scripts/`: experiment runner and saved-data verification
- `docker-compose.yml` and `docker/`: cluster and runner configuration
- [Experiment records](results/final-316-20260924/README.md)
- `tests/` and `trajectories/`: unit tests and synthetic checker fixtures

## Verify the saved results

With Python 3.11 or later, run from the project root:

```bash
python3 scripts/summarize_completed.py
```

No database or third-party Python packages are needed. This checks the archived
source and data hashes, replays all 316 classifications, and verifies recorded
fault, probe and recovery evidence. It writes `audit.json` and
`matrix-summary.json` in the results directory.

## Run the experiments

Use a dedicated Docker daemon with four CPU cores and about 8 GB RAM.
For a dedicated Colima profile on macOS:

```bash
colima start dsa5208 --cpu 4 --memory 8 --disk 25 \
  --vm-type vz --mount "$(pwd):w" --activate=false --ssh-config=false
export DOCKER_CONTEXT=colima-dsa5208
```

Build and start the cluster, then run the workload:

```bash
docker compose build cassandra1 runner
docker compose up -d --wait cassandra1 cassandra2 cassandra3
docker compose run --rm --no-deps runner \
  python scripts/reproduce_independent.py --cases 316
```

Use `docker-compose` if Compose is installed as a standalone command.
`--cases 36` runs one full block. The runner uses fresh keys, a new keyspace
and a separate output directory. It follows the recorded seeded case order
and applies the second collection phase's preparation policy throughout.
Exact results may vary. The report describes the two collection phases,
preparation interruptions and sample-selection method.

The runner uses the dedicated Docker socket to control the three lab containers.
Run one suite at a time. Preparation or control failures stop the suite and
preserve the evidence.

## Run the unit tests

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev,cassandra]'
pytest -q
```

Synthetic trajectories are checker fixtures. The measured results are stored
under `results/final-316-20260924/`.

## Stop the lab

```bash
docker compose stop
colima stop dsa5208
```

The Colima command applies when using the optional dedicated profile.
Stopping retains the database data.
