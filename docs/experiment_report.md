# Experiment Report: Client-Centric Consistency Trajectory Runner

## Summary

This project implements a trajectory-based test harness for client-centric
consistency properties in Cassandra-compatible systems. The current codebase
supports deterministic mock execution for CI, a Cassandra/ScyllaDB executor for
real database runs, and a Docker-backed failure controller for node stop/start
and network partition/heal operations.

The CI experiment validates that the checker logic, trajectory runner,
Cassandra executor adapter, Docker failure-control command generation, and CLI
entrypoint all work on Python 3.11 and 3.12.

## Research Question

Can a small trajectory runner express and check common client-centric
consistency guarantees under different database observations and failure
scenarios?

The implemented properties are:

- Read-your-writes
- Monotonic reads
- Monotonic writes
- Writes-follow-reads

The supported Cassandra consistency levels for real database experiments are:

- `ONE`
- `QUORUM`
- `ALL`

## System Under Test

The repository contains three layers:

- `runner`: loads trajectory JSON files and executes each step.
- `executor`: converts each step into an observed history event.
- `checker`: evaluates a consistency property over the observed history.

Two executor modes are available:

- `MockExecutor`: deterministic observations defined in trajectory files.
- `CassandraExecutor`: real Cassandra/ScyllaDB reads, writes, and audit queries.

The Docker failure controller maps failure steps to Docker commands:

| Trajectory step | Docker action |
| --- | --- |
| `partition N3` | `docker network disconnect -f project1-net project1-cassandra3` |
| `heal N3` | `docker network connect project1-net project1-cassandra3` |
| `stop N2` | `docker stop project1-cassandra2` |
| `start N2` | `docker start project1-cassandra2` |

## Experiment Design

The CI experiment intentionally avoids starting a real Cassandra cluster.
Instead, it validates the experiment harness with deterministic inputs:

- Unit tests cover all four consistency checkers.
- Trajectory tests replay canonical histories from `trajectories/*.json`.
- Cassandra executor tests use a fake session to verify generated observations.
- Failure-control tests use a fake command runner to verify Docker commands.
- A CLI smoke test runs `python -m project1.cli trajectories/ryw_pass.json`.

This design keeps CI reliable while preserving a real execution path for local
or lab-machine Cassandra/ScyllaDB experiments.

## CI Results

Results were collected with GitHub CLI/API from repository
`Erchiusx/dsa5208`.

Latest checked run:

- Workflow: `ci`
- Run ID: `33514078987`
- Commit: `066c4d694b2ccd30132e7972513bf475938a257b`
- Branch: `master`
- Event: `push`
- Status: `completed`
- Conclusion: `success`
- Created: `2026-09-01T13:33:16Z`
- Completed: `2026-09-01T13:33:30Z`
- URL: `https://github.com/Erchiusx/dsa5208/actions/runs/33514078987`

Job results:

| Job | Python | Result | Test output | CLI smoke test |
| --- | --- | --- | --- | --- |
| `test (3.11)` | 3.11.16 | success | `15 passed in 0.04s` | `ryw_pass` returned `PASS` |
| `test (3.12)` | 3.12.14 | success | `15 passed in 0.06s` | `ryw_pass` returned `PASS` |

Local verification was also run in the `default` conda environment:

```bash
conda run -n default python -m pytest -q
```

Result:

```text
15 passed in 0.02s
```

The CLI was verified locally with:

```bash
PYTHONPATH=src python -m project1.cli trajectories/ryw_pass.json
```

Result:

```text
trajectory: ryw_pass
property:   read_your_writes
status:     PASS
reason:     Every successful post-write read was at least as new as the client's latest successful write.
```

## Trajectory Results

The deterministic trajectory suite encodes expected observations for canonical
client-centric consistency cases.

| Trajectory | Property | Expected status | Purpose |
| --- | --- | --- | --- |
| `ryw_pass.json` | Read-your-writes | `PASS` | Client reads the value it previously wrote. |
| `ryw_partition_violation.json` | Read-your-writes | `VIOLATION` | Client writes through one node, then reads stale data from another node. |
| `monotonic_reads_violation.json` | Monotonic reads | `VIOLATION` | Client observes a newer version and later reads an older version. |
| `monotonic_writes_violation.json` | Monotonic writes | `VIOLATION` | Audit order observes a client's later write before its earlier write. |
| `writes_follow_reads_violation.json` | Writes-follow-reads | `VIOLATION` | Observer sees an effect but later misses its required cause. |

## Interpretation

The results show that the current harness can express the target consistency
properties and detect violations in controlled histories. The same trajectory
format can now be run against a Cassandra-compatible database through
`CassandraExecutor`.

For CI, the important result is that all deterministic checks pass across two
Python versions and that the installed package exposes a working CLI entrypoint.
This reduces the risk that later real-cluster experiments are blocked by
packaging, import, or runner regressions.

## Limitations

The CI results are not evidence that Cassandra or ScyllaDB violates or
satisfies the listed properties under real failures. CI does not start a real
cluster, does not execute Docker network partitions, and does not measure
replica propagation timing.

The real-cluster path is implemented but must be run in an environment with:

- Docker and Docker Compose.
- The optional Cassandra Python driver.
- Enough resources for a three-node Cassandra-compatible cluster.

## Reproducing Real-Cluster Experiments

Install dependencies:

```bash
python -m pip install -e ".[dev,cassandra]"
```

Start the cluster:

```bash
docker compose up -d
```

Run a real Cassandra-backed trajectory:

```bash
python -m project1.cli \
  --executor cassandra \
  --failure-controller docker \
  --contact-points 127.0.0.1 \
  --consistency ONE \
  trajectories/ryw_pass.json
```

Repeat with `--consistency QUORUM` and `--consistency ALL` to compare behavior
across consistency levels.

## Conclusion

The project now has a CI-validated experiment harness and a concrete path for
real Cassandra/ScyllaDB experiments. The current automated evidence validates
the checker, runner, executor adapter, Docker failure-control mapping, and CLI.
The next experimental step is to run the same trajectories against a live
three-node cluster and record the observed histories for each consistency level.
