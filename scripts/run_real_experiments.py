from __future__ import annotations

import re
import subprocess
import sys
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Experiment:
    name: str
    trajectory: str
    consistency: str
    keyspace: str
    expected_status: str
    failure_controller: str = "none"


EXPERIMENTS = [
    Experiment("ryw_pass_one", "trajectories/ryw_pass.json", "ONE", "ci_ryw_pass_one", "PASS"),
    Experiment("ryw_pass_quorum", "trajectories/ryw_pass.json", "QUORUM", "ci_ryw_pass_quorum", "PASS"),
    Experiment("ryw_pass_all", "trajectories/ryw_pass.json", "ALL", "ci_ryw_pass_all", "PASS"),
    Experiment("monotonic_reads_one", "trajectories/monotonic_reads_violation.json", "ONE", "ci_mr_one", "PASS"),
    Experiment("monotonic_writes_one", "trajectories/monotonic_writes_violation.json", "ONE", "ci_mw_one", "PASS"),
    Experiment("writes_follow_reads_one", "trajectories/writes_follow_reads_violation.json", "ONE", "ci_wfr_one", "PASS"),
    Experiment(
        "ryw_partition_one",
        "trajectories/ryw_partition_violation.json",
        "ONE",
        "ci_ryw_partition_one",
        "INCONCLUSIVE",
        failure_controller="docker",
    ),
]


def main() -> int:
    wait_for_ring()

    results: list[tuple[Experiment, str, str]] = []
    try:
        for experiment in EXPERIMENTS:
            output = run_experiment(experiment)
            status = parse_status(output)
            results.append((experiment, status, output))
            if status != experiment.expected_status:
                print(output)
                print(
                    f"{experiment.name}: expected {experiment.expected_status}, got {status}",
                    file=sys.stderr,
                )
                return 1
    finally:
        heal_partitioned_node()

    print("\nReal Cassandra experiment summary:")
    for experiment, status, _ in results:
        print(
            f"- {experiment.name}: {status} "
            f"(consistency={experiment.consistency}, failure_controller={experiment.failure_controller})"
        )

    return 0


def wait_for_ring(timeout_seconds: int = 360) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_output = ""
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", "project1-cassandra1", "nodetool", "status"],
            check=False,
            capture_output=True,
            text=True,
        )
        last_output = result.stdout + result.stderr
        if result.returncode == 0 and count_un_nodes(result.stdout) >= 3:
            print(result.stdout)
            return
        time.sleep(10)

    raise RuntimeError(f"Cassandra ring did not reach three UN nodes:\n{last_output}")


def count_un_nodes(output: str) -> int:
    return sum(1 for line in output.splitlines() if line.startswith("UN  "))


def run_experiment(experiment: Experiment) -> str:
    command = [
        sys.executable,
        "-m",
        "project1.cli",
        "--executor",
        "cassandra",
        "--failure-controller",
        experiment.failure_controller,
        "--contact-points",
        "127.0.0.1",
        "--node-ports",
        "N1:9042,N2:9043,N3:9044",
        "--replication-factor",
        "3",
        "--consistency",
        experiment.consistency,
        "--keyspace",
        experiment.keyspace,
        experiment.trajectory,
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    output = result.stdout + result.stderr
    print(f"\n=== {experiment.name} ===")
    print(output)
    if result.returncode != 0:
        raise RuntimeError(f"{experiment.name} failed with exit code {result.returncode}")
    return output


def parse_status(output: str) -> str:
    match = re.search(r"^status:\s+(\w+)$", output, re.MULTILINE)
    if not match:
        raise RuntimeError(f"could not parse status from output:\n{output}")
    return match.group(1)


def heal_partitioned_node() -> None:
    subprocess.run(
        ["docker", "network", "connect", "project1-net", "project1-cassandra3"],
        check=False,
        capture_output=True,
        text=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
