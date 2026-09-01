from __future__ import annotations

from typing import Any

from .executor import Executor
from .model import Observation


class MockExecutor(Executor):
    """
    Deterministic executor for unit tests and CI.

    It does NOT model Cassandra. Instead, each client operation can specify
    its expected observation under a `mock` field. The purpose is to test
    trajectory plumbing and consistency predicates independently from the DB.
    """

    def execute(self, index: int, step: dict[str, Any]) -> Observation:
        mock = step.get("mock", {})
        status = mock.get("status", "ok")

        return Observation(
            index=index,
            op=step["op"],
            status=status,
            client=step.get("client"),
            node=step.get("node"),
            key=step.get("key"),
            version=mock.get("version", step.get("version")),
            write_id=step.get("write_id"),
            seq=step.get("seq"),
            depends_on=step.get("depends_on"),
            order=mock.get("order", step.get("order")),
            raw={"step": step, "mock": mock},
        )
