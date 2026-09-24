from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Protocol


class FailureController(Protocol):
    def apply(self, step: dict[str, Any]) -> dict[str, Any]: ...


class CommandRunner(Protocol):
    def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]: ...


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
            return {
                "status": "unsupported",
                "reason": f"unsupported failure op: {op}",
                "step": step,
            }

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
            return [
                "docker",
                "exec",
                "-u",
                "0",
                container,
                "sh",
                "-ec",
                firewall_script(True),
            ]
        if op == "heal":
            return [
                "docker",
                "exec",
                "-u",
                "0",
                container,
                "sh",
                "-ec",
                firewall_script(False),
            ]
        if op == "stop":
            return ["docker", "stop", container]
        if op == "start":
            return ["docker", "start", container]
        return None

    @staticmethod
    def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, check=False, capture_output=True, text=True)


FIREWALL_CHAIN = "DSA5208_ISOLATE"


def firewall_script(enabled: bool) -> str:
    """Block internode request AND response traffic; preserve CQL/JMX access.

    Only our dedicated chain/hooks are removed during cleanup. No host firewall
    or unrelated container rules are changed.
    """
    chain = FIREWALL_CHAIN
    if enabled:
        return f"""iptables -w 5 -N {chain} 2>/dev/null || true
iptables -w 5 -F {chain}
iptables -w 5 -A {chain} -p tcp -m multiport --dports 7000,7001 -j DROP
iptables -w 5 -A {chain} -p tcp -m multiport --sports 7000,7001 -j DROP
iptables -w 5 -C INPUT -j {chain} 2>/dev/null || iptables -w 5 -I INPUT 1 -j {chain}
iptables -w 5 -C OUTPUT -j {chain} 2>/dev/null || iptables -w 5 -I OUTPUT 1 -j {chain}
iptables -w 5 -C INPUT -j {chain}
iptables -w 5 -C OUTPUT -j {chain}
iptables -w 5 -S {chain}
"""
    return f"""if iptables -w 5 -C INPUT -j {chain} 2>/dev/null; then iptables -w 5 -D INPUT -j {chain}; fi
if iptables -w 5 -C OUTPUT -j {chain} 2>/dev/null; then iptables -w 5 -D OUTPUT -j {chain}; fi
if iptables -w 5 -nL {chain} >/dev/null 2>&1; then iptables -w 5 -F {chain}; iptables -w 5 -X {chain}; fi
iptables -w 5 -S
"""
