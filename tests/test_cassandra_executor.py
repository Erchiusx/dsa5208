from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from project1.cassandra_executor import CassandraConfig, CassandraExecutor
from project1.failure_control import NoopFailureController


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, tuple[Any, ...] | None]] = []
        self.rows_by_key: dict[str, SimpleNamespace] = {}

    def execute(
        self, query: Any, parameters: tuple[Any, ...] | None = None
    ) -> list[SimpleNamespace]:
        self.calls.append((query, parameters))
        text = str(query)
        if "SELECT version" in text:
            key = parameters[0] if parameters else ""
            row = self.rows_by_key.get(key)
            return [] if row is None else [row]
        if "SELECT write_id" in text:
            return [SimpleNamespace(write_id="A1"), SimpleNamespace(write_id="A2")]
        return []


def test_cassandra_executor_write_read_and_audit_observations() -> None:
    session = FakeSession()
    session.rows_by_key["x"] = SimpleNamespace(version=2, write_id="A2", client="A", seq=2)
    executor = CassandraExecutor(
        CassandraConfig(keyspace="ks", replication_factor=1),
        session=session,
    )

    executor.execute(0, {"op": "connect", "client": "A", "node": "N1"})
    write = executor.execute(
        1,
        {
            "op": "write",
            "client": "A",
            "key": "x",
            "version": 2,
            "write_id": "A2",
            "seq": 2,
        },
    )
    read = executor.execute(2, {"op": "read", "client": "A", "key": "x"})
    audit = executor.execute(3, {"op": "audit_order"})

    assert write.status == "ok"
    assert write.node == "N1"
    assert read.version == 2
    assert audit.status == "unsupported"
    assert read.write_id == "A2"
    inserts = [str(q) for q, _ in session.calls if "INSERT INTO" in str(q)]
    assert len(inserts) == 1
    assert "write_audit" not in inserts[0]


def test_cassandra_executor_uses_configured_failure_controller() -> None:
    class FakeFailureController:
        def apply(self, step: dict[str, Any]) -> dict[str, Any]:
            return {
                "status": "ok",
                "step": step,
                "command": ["docker", "stop", "project1-cassandra3"],
            }

    executor = CassandraExecutor(
        CassandraConfig(replication_factor=1),
        session=FakeSession(),
        failure_controller=FakeFailureController(),
    )

    observed = executor.execute(0, {"op": "stop", "node": "N3"})

    assert observed.status == "ok"
    assert observed.raw["command"] == ["docker", "stop", "project1-cassandra3"]


def test_noop_failure_controller_skips_external_failure_controls() -> None:
    executor = CassandraExecutor(
        CassandraConfig(replication_factor=1),
        session=FakeSession(),
        failure_controller=NoopFailureController(),
    )

    observed = executor.execute(0, {"op": "partition", "node": "N3"})

    assert observed.status == "skipped"
    assert observed.raw["reason"] == "no failure controller configured"


def test_data_write_is_not_conflated_with_audit_failure():
    class FailAudit(FakeSession):
        def execute(self, query, parameters=None):
            if "INSERT INTO" in str(query) and "write_audit" in str(query):
                raise RuntimeError("audit unavailable")
            return super().execute(query, parameters)

    executor = CassandraExecutor(CassandraConfig(), session=FailAudit())
    e = executor.execute(0, {"op": "write", "client": "A", "key": "x", "version": 1})
    assert e.status == "ok"


def test_error_keeps_node_exception_and_timing():
    class FailRead(FakeSession):
        def execute(self, query, parameters=None):
            if "SELECT version" in str(query):
                raise TimeoutError("diagnostic timeout")
            return super().execute(query, parameters)

    executor = CassandraExecutor(CassandraConfig(), session=FailRead())
    e = executor.execute(0, {"op": "read", "node": "N3", "client": "A", "key": "x"})
    assert e.status == "error" and e.node == "N3"
    assert e.raw["error_type"] == "TimeoutError"
    assert "diagnostic timeout" in e.raw["error"]
    assert e.raw["duration_ms"] >= 0 and e.raw["started_ns"] > 0
