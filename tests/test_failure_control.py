from __future__ import annotations

import subprocess

from project1.failure_control import DockerFailureController


class RecordingRunner:
    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        return subprocess.CompletedProcess(args, self.returncode, "out", "err")


def test_docker_failure_controller_partitions_and_heals_node() -> None:
    runner = RecordingRunner()
    controller = DockerFailureController(network="net", runner=runner)

    partitioned = controller.apply({"op": "partition", "node": "N3"})
    healed = controller.apply({"op": "heal", "node": "N3"})

    assert partitioned["status"] == "ok"
    assert healed["status"] == "ok"
    assert runner.calls == [
        ["docker", "network", "disconnect", "-f", "net", "project1-cassandra3"],
        ["docker", "network", "connect", "net", "project1-cassandra3"],
    ]


def test_docker_failure_controller_stops_and_starts_node() -> None:
    runner = RecordingRunner()
    controller = DockerFailureController(runner=runner)

    stopped = controller.apply({"op": "stop", "node": "N2"})
    started = controller.apply({"op": "start", "node": "N2"})

    assert stopped["status"] == "ok"
    assert started["status"] == "ok"
    assert runner.calls == [
        ["docker", "stop", "project1-cassandra2"],
        ["docker", "start", "project1-cassandra2"],
    ]


def test_docker_failure_controller_reports_command_failure() -> None:
    runner = RecordingRunner(returncode=1)
    controller = DockerFailureController(runner=runner)

    result = controller.apply({"op": "partition", "node": "N1"})

    assert result["status"] == "error"
    assert result["returncode"] == 1
