from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from .executor import Executor
from .failure_control import FailureController, NoopFailureController
from .model import Observation


class SessionLike(Protocol):
    def execute(self, query: Any, parameters: tuple[Any, ...] | None = None) -> Any:
        ...


@dataclass(frozen=True)
class CassandraConfig:
    contact_points: tuple[str, ...] = ("127.0.0.1",)
    port: int = 9042
    keyspace: str = "project1"
    table: str = "kv"
    audit_table: str = "write_audit"
    replication_factor: int = 3
    default_consistency: str = "ONE"

    @classmethod
    def from_env(cls) -> CassandraConfig:
        points = os.getenv("PROJECT1_CASSANDRA_CONTACT_POINTS", "127.0.0.1")
        return cls(
            contact_points=tuple(p.strip() for p in points.split(",") if p.strip()),
            port=int(os.getenv("PROJECT1_CASSANDRA_PORT", "9042")),
            keyspace=os.getenv("PROJECT1_CASSANDRA_KEYSPACE", "project1"),
            table=os.getenv("PROJECT1_CASSANDRA_TABLE", "kv"),
            audit_table=os.getenv("PROJECT1_CASSANDRA_AUDIT_TABLE", "write_audit"),
            replication_factor=int(os.getenv("PROJECT1_CASSANDRA_REPLICATION_FACTOR", "3")),
            default_consistency=os.getenv("PROJECT1_CASSANDRA_CONSISTENCY", "ONE"),
        )


class CassandraExecutor(Executor):
    """Executor backed by Cassandra or ScyllaDB using the DataStax Python driver."""

    def __init__(
        self,
        config: CassandraConfig | None = None,
        session: SessionLike | None = None,
        failure_controller: FailureController | None = None,
    ) -> None:
        self.config = config or CassandraConfig.from_env()
        self.client_nodes: dict[str, str] = {}
        self.failure_controller = failure_controller or NoopFailureController()

        if session is None:
            session = self._connect_driver_session()

        self.session = session
        self._ensure_schema()

    def execute(self, index: int, step: dict[str, Any]) -> Observation:
        op = step["op"]
        if op == "connect":
            return self._connect_client(index, step)
        if op == "write":
            return self._write(index, step)
        if op == "read":
            return self._read(index, step)
        if op == "audit_order":
            return self._audit_order(index, step)
        if op in {"partition", "heal", "stop", "start"}:
            return self._unsupported_control(index, step)

        return Observation(index=index, op=op, status="unsupported", raw={"step": step})

    def _connect_driver_session(self) -> SessionLike:
        try:
            from cassandra.cluster import Cluster
        except ImportError as exc:
            raise RuntimeError(
                "Cassandra executor requires the optional dependency: "
                'python -m pip install -e ".[cassandra]"'
            ) from exc

        cluster = Cluster(contact_points=list(self.config.contact_points), port=self.config.port)
        return cluster.connect()

    def _ensure_schema(self) -> None:
        keyspace = self.config.keyspace
        table = self.config.table
        audit_table = self.config.audit_table
        rf = self.config.replication_factor

        self.session.execute(
            f"""
            CREATE KEYSPACE IF NOT EXISTS {keyspace}
            WITH replication = {{'class': 'SimpleStrategy', 'replication_factor': {rf}}}
            """
        )
        self.session.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {keyspace}.{table} (
                item_key text PRIMARY KEY,
                version int,
                write_id text,
                client text,
                seq int
            )
            """
        )
        self.session.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {keyspace}.{audit_table} (
                bucket text,
                seq int,
                write_id text,
                client text,
                item_key text,
                version int,
                PRIMARY KEY (bucket, seq)
            ) WITH CLUSTERING ORDER BY (seq ASC)
            """
        )

    def _connect_client(self, index: int, step: dict[str, Any]) -> Observation:
        client = step.get("client")
        node = step.get("node")
        if client is not None and node is not None:
            self.client_nodes[str(client)] = str(node)
        return Observation(index=index, op="connect", client=client, node=node, raw={"step": step})

    def _write(self, index: int, step: dict[str, Any]) -> Observation:
        key = str(step["key"])
        version = int(step["version"])
        client = step.get("client")
        write_id = step.get("write_id") or f"{client}:{key}:{version}:{index}"
        seq = int(step.get("seq", index))

        try:
            self.session.execute(
                self._statement(
                    f"""
                    INSERT INTO {self.config.keyspace}.{self.config.table}
                    (item_key, version, write_id, client, seq)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    step,
                ),
                (key, version, write_id, client, seq),
            )
            self.session.execute(
                self._statement(
                    f"""
                    INSERT INTO {self.config.keyspace}.{self.config.audit_table}
                    (bucket, seq, write_id, client, item_key, version)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    step,
                ),
                ("default", seq, write_id, client, key, version),
            )
        except Exception as exc:  # pragma: no cover - driver/runtime specific
            return self._error_observation(index, step, exc)

        return Observation(
            index=index,
            op="write",
            client=client,
            node=self.client_nodes.get(str(client)),
            key=key,
            version=version,
            write_id=str(write_id),
            seq=seq,
            depends_on=step.get("depends_on"),
            raw={"step": step},
        )

    def _read(self, index: int, step: dict[str, Any]) -> Observation:
        key = str(step["key"])
        client = step.get("client")

        try:
            rows = self.session.execute(
                self._statement(
                    f"""
                    SELECT version, write_id, client, seq
                    FROM {self.config.keyspace}.{self.config.table}
                    WHERE item_key = %s
                    """,
                    step,
                ),
                (key,),
            )
            row = next(iter(rows), None)
        except Exception as exc:  # pragma: no cover - driver/runtime specific
            return self._error_observation(index, step, exc)

        version = getattr(row, "version", None) if row is not None else 0
        return Observation(
            index=index,
            op="read",
            client=client,
            node=self.client_nodes.get(str(client)),
            key=key,
            version=version,
            raw={"step": step, "row": self._row_dict(row)},
        )

    def _audit_order(self, index: int, step: dict[str, Any]) -> Observation:
        try:
            rows = self.session.execute(
                self._statement(
                    f"""
                    SELECT write_id
                    FROM {self.config.keyspace}.{self.config.audit_table}
                    WHERE bucket = %s
                    """,
                    step,
                ),
                ("default",),
            )
        except Exception as exc:  # pragma: no cover - driver/runtime specific
            return self._error_observation(index, step, exc)

        order = [row.write_id for row in rows if getattr(row, "write_id", None) is not None]
        return Observation(index=index, op="audit_order", order=order, raw={"step": step})

    def _unsupported_control(self, index: int, step: dict[str, Any]) -> Observation:
        result = self.failure_controller.apply(step)
        return Observation(
            index=index,
            op=step["op"],
            status=result["status"],
            node=step.get("node"),
            raw=result,
        )

    def _statement(self, query: str, step: dict[str, Any]) -> Any:
        consistency = step.get("consistency", self.config.default_consistency)
        try:
            from cassandra import ConsistencyLevel
            from cassandra.query import SimpleStatement
        except ImportError:
            return query

        level = getattr(ConsistencyLevel, str(consistency).upper())
        return SimpleStatement(query, consistency_level=level)

    def _error_observation(self, index: int, step: dict[str, Any], exc: Exception) -> Observation:
        return Observation(
            index=index,
            op=step["op"],
            status="error",
            client=step.get("client"),
            node=step.get("node"),
            key=step.get("key"),
            version=step.get("version"),
            write_id=step.get("write_id"),
            seq=step.get("seq"),
            depends_on=step.get("depends_on"),
            raw={"step": step, "error": repr(exc)},
        )

    @staticmethod
    def _row_dict(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        fields = ("version", "write_id", "client", "seq")
        return {name: getattr(row, name, None) for name in fields}
