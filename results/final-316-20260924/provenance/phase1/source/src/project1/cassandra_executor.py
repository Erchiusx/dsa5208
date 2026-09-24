from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .executor import Executor
from .failure_control import NoopFailureController
from .model import Observation


class SessionLike(Protocol):
    def execute(self, query: Any, parameters: tuple[Any, ...] | None = None) -> Any: ...


@dataclass(frozen=True)
class CassandraConfig:
    contact_points: tuple[str, ...] = ("127.0.0.1",)
    port: int = 9042
    keyspace: str = "project1"
    table: str = "kv"
    replication_factor: int = 3
    default_consistency: str = "ONE"
    read_repair: str = "BLOCKING"
    request_timeout: float = 3.0
    node_ports: dict[str, int] = field(default_factory=lambda: {"N1": 9042, "N2": 9043, "N3": 9044})
    node_contact_points: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> CassandraConfig:
        points = os.getenv("PROJECT1_CASSANDRA_CONTACT_POINTS", "127.0.0.1")
        return cls(
            contact_points=tuple(p.strip() for p in points.split(",") if p.strip()),
            port=int(os.getenv("PROJECT1_CASSANDRA_PORT", "9042")),
            keyspace=os.getenv("PROJECT1_CASSANDRA_KEYSPACE", "project1"),
            table=os.getenv("PROJECT1_CASSANDRA_TABLE", "kv"),
            replication_factor=int(os.getenv("PROJECT1_CASSANDRA_REPLICATION_FACTOR", "3")),
            default_consistency=os.getenv("PROJECT1_CASSANDRA_CONSISTENCY", "ONE"),
            node_ports=cls._node_ports_from_env(),
            node_contact_points=cls._node_contact_points_from_env(),
        )

    @staticmethod
    def _node_ports_from_env() -> dict[str, int]:
        raw = os.getenv("PROJECT1_CASSANDRA_NODE_PORTS")
        if not raw:
            return {"N1": 9042, "N2": 9043, "N3": 9044}

        ports: dict[str, int] = {}
        for item in raw.split(","):
            node, port = item.split(":", maxsplit=1)
            ports[node.strip()] = int(port)
        return ports

    @staticmethod
    def _node_contact_points_from_env() -> dict[str, tuple[str, ...]]:
        raw = os.getenv("PROJECT1_CASSANDRA_NODE_CONTACT_POINTS")
        if not raw:
            return {}

        contact_points: dict[str, tuple[str, ...]] = {}
        for item in raw.split(","):
            node, hosts = item.split(":", maxsplit=1)
            contact_points[node.strip()] = tuple(h.strip() for h in hosts.split("+") if h.strip())
        return contact_points


class CassandraExecutor(Executor):
    """One acknowledged data mutation per write; no synthetic order audit."""

    def __init__(self, config=None, session=None, failure_controller=None):
        self.config = config or CassandraConfig.from_env()
        for name in (self.config.keyspace, self.config.table):
            if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
                raise ValueError(f"Invalid CQL identifier: {name}")
        if self.config.read_repair not in {"BLOCKING", "NONE"}:
            raise ValueError("read_repair must be BLOCKING or NONE")
        self.client_nodes = {}
        self.failure_controller = failure_controller or NoopFailureController()
        self._injected_session = session is not None
        self._sessions = {}
        self._clusters = []
        self.session = session or self._connect_driver_session(
            self._contact_points_for_node("N1"),
            self.config.node_ports.get("N1", self.config.port),
        )
        self._ensure_schema()

    def close(self):
        for cluster in self._clusters:
            cluster.shutdown()
        self._clusters.clear()
        self._sessions.clear()

    def execute(self, index, step):
        started = time.time_ns()
        timer = time.perf_counter_ns()
        op = step["op"]
        try:
            if op == "connect":
                client, node = step["client"], step["node"]
                self.client_nodes[client] = node
                result = Observation(index, op, client=client, node=node, raw={"step": step})
            elif op == "write":
                result = self._write(index, step)
            elif op == "read":
                result = self._read(index, step)
            elif op == "audit_order":
                result = Observation(
                    index,
                    op,
                    status="unsupported",
                    raw={
                        "step": step,
                        "reason": "A seq-sorted Cassandra table is not an application-order audit. Use verified dependency probes.",
                    },
                )
            elif op in {"partition", "heal", "stop", "start"}:
                control = self.failure_controller.apply(step)
                result = Observation(
                    index,
                    op,
                    status=control["status"],
                    node=step.get("node"),
                    raw=control,
                )
            else:
                result = Observation(index, op, status="unsupported", raw={"step": step})
        except Exception as exc:
            result = self._error_observation(index, step, exc)
        result.raw.update(
            started_ns=started,
            duration_ms=(time.perf_counter_ns() - timer) / 1e6,
            consistency=step.get("consistency", self.config.default_consistency)
            if op in {"write", "read"}
            else None,
        )
        return result

    def _connect_driver_session(self, contact_points, port):
        from cassandra.cluster import EXEC_PROFILE_DEFAULT, Cluster, ExecutionProfile
        from cassandra.policies import FallthroughRetryPolicy, WhiteListRoundRobinPolicy

        profile = ExecutionProfile(
            load_balancing_policy=WhiteListRoundRobinPolicy(list(contact_points)),
            retry_policy=FallthroughRetryPolicy(),
            request_timeout=self.config.request_timeout,
        )
        cluster = Cluster(
            contact_points=list(contact_points),
            port=port,
            execution_profiles={EXEC_PROFILE_DEFAULT: profile},
            connect_timeout=5,
        )
        self._clusters.append(cluster)
        return cluster.connect()

    def _ensure_schema(self):
        c = self.config
        self.session.execute(
            f"CREATE KEYSPACE IF NOT EXISTS {c.keyspace} WITH replication = {{'class':'SimpleStrategy','replication_factor':{c.replication_factor}}}"
        )
        self.session.execute(f"""CREATE TABLE IF NOT EXISTS {c.keyspace}.{c.table} (
            item_key text PRIMARY KEY, version int, write_id text, client text, seq int)
            WITH read_repair='{c.read_repair}' AND speculative_retry='NONE'""")

    def _node(self, step):
        return step.get("node") or self.client_nodes.get(str(step.get("client")), "N1")

    def _write(self, index, step):
        c = self.config
        client = step.get("client")
        wid = step.get("write_id") or f"{client}:{step['key']}:{step['version']}:{index}"
        seq = int(step.get("seq", index))
        query = f"INSERT INTO {c.keyspace}.{c.table} (item_key,version,write_id,client,seq) VALUES (%s,%s,%s,%s,%s)"
        params = (str(step["key"]), int(step["version"]), wid, client, seq)
        if "timestamp_us" in step:
            query += " USING TIMESTAMP %s"
            params += (int(step["timestamp_us"]),)
        rows = self._session_for_step(step).execute(self._statement(query, step), params)
        return Observation(
            index,
            "write",
            client=client,
            node=self._node(step),
            key=str(step["key"]),
            version=int(step["version"]),
            write_id=str(wid),
            seq=seq,
            depends_on=step.get("depends_on"),
            raw={"step": step, "coordinator": self._coordinator(rows)},
        )

    def _read(self, index, step):
        c = self.config
        rows = self._session_for_step(step).execute(
            self._statement(
                f"SELECT version, write_id, client, seq FROM {c.keyspace}.{c.table} WHERE item_key = %s",
                step,
            ),
            (str(step["key"]),),
        )
        row = next(iter(rows), None)
        return Observation(
            index,
            "read",
            client=step.get("client"),
            node=self._node(step),
            key=str(step["key"]),
            version=getattr(row, "version", None) if row is not None else 0,
            write_id=getattr(row, "write_id", None),
            seq=getattr(row, "seq", None),
            raw={
                "step": step,
                "row": self._row_dict(row),
                "coordinator": self._coordinator(rows),
            },
        )

    def _session_for_step(self, step):
        if self._injected_session:
            return self.session
        node = self._node(step)
        if node == "N1":
            return self.session
        if node not in self.config.node_ports:
            raise ValueError(f"Unknown node {node}; refusing to silently reroute")
        if node not in self._sessions:
            self._sessions[node] = self._connect_driver_session(
                self._contact_points_for_node(node), self.config.node_ports[node]
            )
        return self._sessions[node]

    def _contact_points_for_node(self, node):
        return self.config.node_contact_points.get(node, self.config.contact_points)

    def _statement(self, query, step):
        level = str(step.get("consistency", self.config.default_consistency)).upper()
        if level not in {"ONE", "QUORUM", "ALL"}:
            raise ValueError(f"Unsupported consistency {level}")
        try:
            from cassandra import ConsistencyLevel
            from cassandra.query import SimpleStatement
        except ImportError:
            if self._injected_session:
                return query
            raise
        return SimpleStatement(query, consistency_level=getattr(ConsistencyLevel, level))

    def _error_observation(self, index, step, exc):
        return Observation(
            index,
            step["op"],
            status="error",
            client=step.get("client"),
            node=self._node(step),
            key=step.get("key"),
            version=step.get("version"),
            write_id=step.get("write_id"),
            seq=step.get("seq"),
            depends_on=step.get("depends_on"),
            raw={"step": step, "error": repr(exc), "error_type": type(exc).__name__},
        )

    @staticmethod
    def _coordinator(rows):
        host = getattr(getattr(rows, "response_future", None), "coordinator_host", None)
        return str(host.address) if host is not None else None

    @staticmethod
    def _row_dict(row):
        return (
            {name: getattr(row, name, None) for name in ("version", "write_id", "client", "seq")}
            if row is not None
            else None
        )
