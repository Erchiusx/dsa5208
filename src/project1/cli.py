from __future__ import annotations

import argparse
import json
from dataclasses import replace

from .cassandra_executor import CassandraConfig, CassandraExecutor
from .executor import Executor
from .failure_control import DockerFailureController, NoopFailureController
from .mock_executor import MockExecutor
from .runner import load_trajectory, run_trajectory


def build_executor(args: argparse.Namespace) -> Executor:
    if args.executor == "mock":
        return MockExecutor()

    config = CassandraConfig.from_env()
    config = replace(
        config,
        contact_points=(
            tuple(p.strip() for p in args.contact_points.split(",") if p.strip())
            if args.contact_points
            else config.contact_points
        ),
        port=args.port if args.port is not None else config.port,
        keyspace=args.keyspace if args.keyspace is not None else config.keyspace,
        table=args.table if args.table is not None else config.table,
        audit_table=args.audit_table if args.audit_table is not None else config.audit_table,
        replication_factor=(
            args.replication_factor
            if args.replication_factor is not None
            else config.replication_factor
        ),
        default_consistency=args.consistency if args.consistency is not None else config.default_consistency,
    )
    failure_controller = (
        DockerFailureController.from_env()
        if args.failure_controller == "docker"
        else NoopFailureController()
    )
    return CassandraExecutor(config, failure_controller=failure_controller)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trajectory", help="path to trajectory JSON")
    parser.add_argument(
        "--executor",
        choices=("mock", "cassandra"),
        default="mock",
        help="executor backend to use",
    )
    parser.add_argument("--contact-points", help="comma-separated Cassandra/Scylla contact points")
    parser.add_argument("--port", type=int)
    parser.add_argument("--keyspace")
    parser.add_argument("--table")
    parser.add_argument("--audit-table")
    parser.add_argument("--replication-factor", type=int)
    parser.add_argument("--consistency", choices=("ONE", "QUORUM", "ALL"))
    parser.add_argument(
        "--failure-controller",
        choices=("none", "docker"),
        default="none",
        help="external controller for partition/heal/stop/start steps",
    )
    args = parser.parse_args()

    trajectory = load_trajectory(args.trajectory)
    history, result = run_trajectory(trajectory, build_executor(args))

    print(f"trajectory: {trajectory['name']}")
    print(f"property:   {result.property_name}")
    print(f"status:     {result.status}")
    print(f"reason:     {result.reason}")
    if result.witness:
        print(f"witness:    {result.witness}")

    print("\nhistory:")
    for ev in history:
        print(json.dumps({
            "index": ev.index,
            "op": ev.op,
            "status": ev.status,
            "client": ev.client,
            "node": ev.node,
            "key": ev.key,
            "version": ev.version,
            "write_id": ev.write_id,
            "seq": ev.seq,
            "depends_on": ev.depends_on,
            "order": ev.order,
        }, ensure_ascii=False))

    return 1 if result.status == "VIOLATION" else 0


if __name__ == "__main__":
    raise SystemExit(main())
