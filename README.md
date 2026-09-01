# Consistency Path Lab — v0.1

A small prototype for the distributed-database project.

The first version deliberately **does not do automatic path exploration**.
Instead, it hand-writes a few canonical client trajectories for:

- Read-your-writes (RYW)
- Monotonic reads (MR)
- Monotonic writes (MW)
- Writes-follow-reads (WFR)

The architecture is:

```text
trajectory JSON
    ↓
runner
    ↓
executor
    ↓
observed history
    ↓
property checker
    ↓
PASS / VIOLATION / INCONCLUSIVE
```

The included `MockExecutor` makes CI deterministic. A real Cassandra/ScyllaDB
executor can implement the same `Executor` interface later.

## Repository layout

```text
.
├── .github/workflows/ci.yml
├── pyproject.toml
├── src/project1/
│   ├── __init__.py
│   ├── model.py
│   ├── executor.py
│   ├── failure_control.py
│   ├── mock_executor.py
│   ├── cassandra_executor.py
│   ├── checker.py
│   ├── runner.py
│   └── cli.py
├── trajectories/
│   ├── ryw_partition_violation.json
│   ├── ryw_pass.json
│   ├── monotonic_reads_violation.json
│   ├── monotonic_writes_violation.json
│   └── writes_follow_reads_violation.json
└── tests/
    ├── test_trajectories.py
    └── test_checkers.py
```

## Run locally

```bash
python -m pip install -e ".[dev]"
pytest -q
```

Run one trajectory:

```bash
python -m project1.cli trajectories/ryw_partition_violation.json
```

Run all trajectories:

```bash
for f in trajectories/*.json; do
  python -m project1.cli "$f"
done
```

Run the real Cassandra experiment suite used by CI:

```bash
docker compose up -d
python scripts/run_real_experiments.py
docker compose down
```

## Run against Cassandra or ScyllaDB

The mock executor remains the default for deterministic unit tests. To run a
trajectory against a real Cassandra-compatible cluster, install the optional
driver and select the Cassandra executor:

```bash
python -m pip install -e ".[dev,cassandra]"
docker compose up -d
python -m project1.cli \
  --executor cassandra \
  --failure-controller docker \
  --contact-points 127.0.0.1 \
  --node-contact-points N1:172.20.0.2,N2:172.20.0.3,N3:172.20.0.4 \
  --consistency ONE \
  trajectories/ryw_pass.json
```

Supported consistency levels are `ONE`, `QUORUM`, and `ALL`. The executor
creates two tables in the configured keyspace:

- `kv`: latest observed value per key.
- `write_audit`: per-write audit rows used by the monotonic-writes checker.

Failure-injection steps such as `partition`, `heal`, `stop`, and `start` are
delegated to a pluggable failure controller. `--failure-controller docker`
uses Docker CLI commands against the compose containers:

```text
partition N3 -> docker network disconnect -f project1-net project1-cassandra3
heal N3      -> docker network connect project1-net project1-cassandra3
stop N2      -> docker stop project1-cassandra2
start N2     -> docker start project1-cassandra2
```

The default controller is `none`, which records these steps as skipped. CI uses
that default and validates the Docker controller with fake command runners, so
GitHub Actions does not need a running Cassandra cluster or Docker daemon.

Configuration can be passed via CLI flags or environment variables:

```bash
PROJECT1_CASSANDRA_CONTACT_POINTS=127.0.0.1 \
PROJECT1_CASSANDRA_NODE_CONTACT_POINTS=N1:172.20.0.2,N2:172.20.0.3,N3:172.20.0.4 \
PROJECT1_CASSANDRA_CONSISTENCY=QUORUM \
python -m project1.cli --executor cassandra trajectories/ryw_pass.json
```

## Trajectory format

Example:

```json
{
  "name": "ryw_partition_violation",
  "property": "read_your_writes",
  "steps": [
    {"op": "partition", "node": "N3"},
    {"op": "connect", "client": "A", "node": "N1"},
    {
      "op": "write",
      "client": "A",
      "key": "x",
      "version": 1,
      "mock": {"status": "ok"}
    },
    {"op": "connect", "client": "A", "node": "N3"},
    {
      "op": "read",
      "client": "A",
      "key": "x",
      "mock": {"status": "ok", "version": 0}
    }
  ]
}
```

The `mock` section exists only for the deterministic mock executor.
A real database executor would ignore it and return observations from
the actual database.

## Property contracts in this prototype

### RYW

For each client/key:

```text
successful write(version = v)
...
later read(version = r)

require r >= v
```

### Monotonic reads

For each client/key:

```text
read(v1)
...
read(v2)

require v2 >= v1
```

### Monotonic writes

This prototype uses an explicit `audit_order` operation. The executor is
expected to return the backend-observed application order of write IDs.

If a client issued:

```text
A1(seq=1)
A2(seq=2)
```

then the audited order must not contain:

```text
A2, A1
```

For a real database, this needs instrumentation (for example, an append-only
audit table or another observation mechanism).

### Writes-follow-reads

A write may carry a dependency on a value previously read:

```text
A reads x=v1
A writes y=v1 depends_on x>=v1
```

If observer C later sees `y=v1`, then C must not subsequently observe
`x<v1`.

## Next step

Implement a real `CassandraExecutor` / `ScyllaExecutor` supporting:

- connect(client, node)
- read(client, key, CL)
- write(client, key, version, CL)
- partition/heal
- stop/start node
- structured event logging

Then replay the exact same hand-written trajectories against the real cluster.
