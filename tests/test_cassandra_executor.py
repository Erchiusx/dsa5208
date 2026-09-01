from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from project1.cassandra_executor import CassandraConfig, CassandraExecutor


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, tuple[Any, ...] | None]] = []
        self.rows_by_key: dict[str, SimpleNamespace] = {}

    def execute(self, query: Any, parameters: tuple[Any, ...] | None = None) -> list[SimpleNamespace]:
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
        {"op": "write", "client": "A", "key": "x", "version": 2, "write_id": "A2", "seq": 2},
    )
    read = executor.execute(2, {"op": "read", "client": "A", "key": "x"})
    audit = executor.execute(3, {"op": "audit_order"})

    assert write.status == "ok"
    assert write.node == "N1"
    assert read.version == 2
    assert audit.order == ["A1", "A2"]


def test_cassandra_executor_marks_external_failure_controls_as_skipped() -> None:
    executor = CassandraExecutor(CassandraConfig(replication_factor=1), session=FakeSession())

    observed = executor.execute(0, {"op": "partition", "node": "N3"})

    assert observed.status == "skipped"
    assert observed.raw["reason"] == "cluster failure injection is external to CassandraExecutor"
