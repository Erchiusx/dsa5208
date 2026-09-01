from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Protocol


class FailureController(Protocol):
    def apply(self, step: dict[str, Any]) -> dict[str, Any]:
        ...


class CommandRunner(Protocol):
    def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        ...


class NoopFailureController:
    def apply(self, step: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "skipped",
            "reason": "no failure controller configured",
            "step": step,
        }


@dataclass
class DockerFailureController:
    network: str = "project1-net"
    node_containers: dict[str, str] = field(default_factory=dict)
    runner: CommandRunner | None = None

    @classmethod
    def from_env(cls) -> DockerFailureController:
        network = os.getenv("PROJECT1_DOCKER_NETWORK", "project1-net")
        return cls(network=network)

    def __post_init__(self) -> None:
        if not self.node_containers:
            self.node_containers = {
                "N1": "project1-cassandra1",
                "N2": "project1-cassandra2",
                "N3": "project1-cassandra3",
            }
        if self.runner is None:
            self.runner = self._run

    def apply(self, step: dict[str, Any]) -> dict[str, Any]:
        op = step["op"]
        node = step.get("node")
        if node is None:
            return {"status": "error", "reason": f"{op} requires a node", "step": step}

        container = self.node_containers.get(str(node))
        if container is None:
            return {"status": "error", "reason": f"unknown node: {node}", "step": step}

        command = self._command(op, container)
        if command is None:
            return {"status": "unsupported", "reason": f"unsupported failure op: {op}", "step": step}

        result = self.runner(command)
        status = "ok" if result.returncode == 0 else "error"
        return {
            "status": status,
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "step": step,
        }

    def _command(self, op: str, container: str) -> list[str] | None:
        if op == "partition":
            return ["docker", "network", "disconnect", "-f", self.network, container]
        if op == "heal":
            return ["docker", "network", "connect", self.network, container]
        if op == "stop":
            return ["docker", "stop", container]
        if op == "start":
            return ["docker", "start", container]
        return None

    @staticmethod
    def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, check=False, capture_output=True, text=True)
