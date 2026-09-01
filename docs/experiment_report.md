# Experiment Report: Client-Centric Consistency Trajectory Runner

## Summary

This project implements a trajectory-based test harness for client-centric
consistency properties in Cassandra-compatible systems. The current codebase
supports deterministic mock execution for CI, a Cassandra/ScyllaDB executor for
real database runs, and a Docker-backed failure controller for node stop/start
and network partition/heal operations.

The CI experiment validates that the checker logic, trajectory runner,
Cassandra executor adapter, Docker failure-control command generation, and CLI
entrypoint all work on Python 3.11 and 3.12. The full Cassandra experiment is
kept as a local/lab-machine experiment because a three-node Cassandra cluster is
too resource-heavy for the GitHub-hosted runner used by this repository.

The real database experiment runs the same canonical trajectories against a
three-node Cassandra 5.0 cluster managed by Docker Compose.

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
or lab-machine Cassandra/ScyllaDB experiments. A trial CI job that started the
three-node Cassandra cluster reached the experiment step but was killed with
exit code 137, which indicates runner resource exhaustion. For that reason the
final CI workflow runs deterministic harness tests only, while the real
Cassandra results below come from the local Docker Compose run.

The real database run starts three Cassandra containers and pins client
operations to specific nodes using per-node contact points:

| Logical node | Container | Contact point |
| --- | --- | --- |
| `N1` | `project1-cassandra1` | `172.21.0.2:9042` |
| `N2` | `project1-cassandra2` | `172.21.0.3:9042` |
| `N3` | `project1-cassandra3` | `172.21.0.4:9042` |

Cluster status before the real trajectory run:

```text
Datacenter: dc1
===============
Status=Up/Down
|/ State=Normal/Leaving/Joining/Moving
--  Address     Load        Tokens  Owns (effective)  Rack
UN  172.21.0.4  105.63 KiB  16      100.0%            rack1
UN  172.21.0.3  102.14 KiB  16      100.0%            rack1
UN  172.21.0.2  129.15 KiB  16      100.0%            rack1
```

## CI Results

Results were collected with GitHub CLI/API from repository
`Erchiusx/dsa5208`.

Validation run:

- Workflow: `ci`
- Run ID: `33515585123`
- Commit: `18cc8709e469a1efc4d63cba969a78863a6f56d0`
- Branch: `master`
- Event: `push`
- Status: `completed`
- Conclusion: `success`
- Created: `2026-09-01T13:48:05Z`
- Completed: `2026-09-01T13:48:22Z`
- URL: `https://github.com/Erchiusx/dsa5208/actions/runs/33515585123`

Job results:

| Job | Python | Result | Test output | CLI smoke test |
| --- | --- | --- | --- | --- |
| `test (3.11)` | 3.11.16 | success | `15 passed in 0.06s` | `ryw_pass` returned `PASS` |
| `test (3.12)` | 3.12.14 | success | `15 passed in 0.04s` | `ryw_pass` returned `PASS` |

The final workflow intentionally does not start the real Cassandra cluster. The
real cluster experiment is reproducible with the commands in the reproduction
section and was run locally for the results below.

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

## Mock Trajectory Results

The deterministic trajectory suite encodes expected observations for canonical
client-centric consistency cases.

| Trajectory | Property | Expected status | Purpose |
| --- | --- | --- | --- |
| `ryw_pass.json` | Read-your-writes | `PASS` | Client reads the value it previously wrote. |
| `ryw_partition_violation.json` | Read-your-writes | `VIOLATION` | Client writes through one node, then reads stale data from another node. |
| `monotonic_reads_violation.json` | Monotonic reads | `VIOLATION` | Client observes a newer version and later reads an older version. |
| `monotonic_writes_violation.json` | Monotonic writes | `VIOLATION` | Audit order observes a client's later write before its earlier write. |
| `writes_follow_reads_violation.json` | Writes-follow-reads | `VIOLATION` | Observer sees an effect but later misses its required cause. |

## Real Cassandra Results

The following commands were run against the live Docker Compose Cassandra
cluster using `cassandra-driver 3.30.1`.

Common arguments:

```bash
python -m project1.cli \
  --executor cassandra \
  --contact-points 172.21.0.2 \
  --node-contact-points N1:172.21.0.2,N2:172.21.0.3,N3:172.21.0.4 \
  --node-ports N1:9042,N2:9042,N3:9042 \
  --replication-factor 3
```

Observed results:

| Trajectory | Consistency | Failure controller | Real result | Key observation |
| --- | --- | --- | --- | --- |
| `ryw_pass.json` | `ONE` | `none` | `PASS` | Write on `N1` and later read on `N1` returned version 1. |
| `ryw_pass.json` | `QUORUM` | `none` | `PASS` | Same read-your-writes path passed at quorum. |
| `ryw_pass.json` | `ALL` | `none` | `PASS` | Same read-your-writes path passed at all replicas. |
| `monotonic_reads_violation.json` | `ONE` | `none` | `PASS` | Both reads returned version 0, so no backward read occurred. |
| `monotonic_writes_violation.json` | `ONE` | `none` | `PASS` | Audit observed monotonic order instead of the mock's reversed order. |
| `writes_follow_reads_violation.json` | `ONE` | `none` | `PASS` | Observer read both effect `y=1` and cause `x=1`. |
| `ryw_partition_violation.json` | `ONE` | `docker` | `INCONCLUSIVE` | `partition N3` succeeded, write on `N1` succeeded, read from isolated `N3` failed instead of returning stale data. |

The partition run produced this history shape:

```text
partition N3: ok
connect A -> N1: ok
write A x=1 on N1: ok
connect A -> N3: ok
read A x from N3: error
checker result: INCONCLUSIVE
```

## Interpretation

The results show that the current harness can express the target consistency
properties and detect violations in controlled histories. The same trajectory
format can now be run against a Cassandra-compatible database through
`CassandraExecutor`.

For CI, the important result is that all deterministic checks pass across two
Python versions and that the installed package exposes a working CLI entrypoint.
This reduces the risk that later real-cluster experiments are blocked by
packaging, import, or runner regressions.

For the real Cassandra run, the canonical mock violations did not automatically
reproduce as database violations. This is expected: the mock files encode
specific stale or reordered observations, while the live cluster produced either
consistent reads or an unavailable isolated node. In particular, disconnecting
`N3` from the Docker network made reads from `N3` fail rather than return a
stale value.

## Limitations

The CI results are not evidence that Cassandra or ScyllaDB violates or
satisfies the listed properties under real failures. CI does not start a real
cluster or execute Docker network partitions.

The local real-cluster run is evidence that the Cassandra executor can issue
real reads and writes and that Docker failure control can isolate a node.
However, it does not yet search timing windows or repair/anti-entropy behavior,
so it should not be interpreted as a complete consistency analysis of
Cassandra.

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

The project now has a CI-validated experiment harness plus a completed local
three-node Cassandra run. The automated evidence validates the checker, runner,
executor adapter, Docker failure-control mapping, and CLI. The local database
evidence shows that the canonical trajectories execute against Cassandra 5.0:
the normal read-your-writes path passes at `ONE`, `QUORUM`, and `ALL`; the
mock-only stale/reordered violation paths do not reproduce as live Cassandra
violations; and the Docker partition path isolates `N3`, producing an
unavailable read rather than a stale read.
