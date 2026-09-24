"""Reproducible Cassandra experiments; run in the Compose runner container.

Each scenario is one fault episode with repeated, unique-key workloads. MW/WFR
are immutable-dependency visibility probes, not claims about every internal
application order. Setup and observation probes are separate from workload CL.
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import socket
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import docker
from project1.cassandra_executor import CassandraConfig, CassandraExecutor
from project1.checker import check
from project1.failure_control import FIREWALL_CHAIN, firewall_script
from project1.model import CheckResult, Observation

PROPERTIES = [
    "read_your_writes",
    "monotonic_reads",
    "monotonic_writes",
    "writes_follow_reads",
]
LEVELS = ["ONE", "QUORUM", "ALL"]
SCENARIOS = ["normal", "node_stop", "partition"]
NAMES = {f"N{i}": f"project1-cassandra{i}" for i in range(1, 4)}


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")


def prediction(scenario, level, prop):
    if scenario == "normal":
        return "No violation expected in this healthy sequential workload; not a general guarantee."
    if scenario == "node_stop":
        return (
            "Prerequisite/read cannot meet ALL; expect INCONCLUSIVE with failed requests."
            if level == "ALL"
            else "Live-side operations can complete; no violation expected in this workload."
        )
    if level == "ONE":
        return (
            "Expect an older successful read across the partition."
            if prop in PROPERTIES[:2]
            else "Expect effect on majority side without its isolated-side predecessor."
        )
    return "At least one prerequisite/read cannot obtain enough responses; expect INCONCLUSIVE."


class LabControl:
    def __init__(self, out):
        self.api = docker.from_env()
        self.containers = {n: self.api.containers.get(name) for n, name in NAMES.items()}
        self.addresses = {}
        for n, c in self.containers.items():
            c.reload()
            self.addresses[n] = c.attrs["NetworkSettings"]["Networks"]["project1-net"]["IPAddress"]
            if not self.addresses[n]:
                raise RuntimeError(f"No lab IP for {n}")
        self.log = (out / "controls.jsonl").open("w")
        self.counter = 0

    def record(self, op, node, **fields):
        self.counter += 1
        event = {
            "control_id": self.counter,
            "time_ns": time.time_ns(),
            "op": op,
            "node": node,
            **fields,
        }
        self.log.write(json.dumps(event, default=str) + "\n")
        self.log.flush()
        return event

    def exec(self, node, args, check_ok=True):
        r = self.containers[node].exec_run(args, user="0")
        text = r.output.decode(errors="replace")
        if check_ok and r.exit_code:
            raise RuntimeError(f"{node}: {args}: {r.exit_code}: {text}")
        return r.exit_code, text

    def peer_tcp(self, source, target):
        return self.exec(
            source,
            [
                "bash",
                "-c",
                f"timeout 2 bash -c ': > /dev/tcp/{self.addresses[target]}/7000'",
            ],
            False,
        )[0]

    def set_isolated(self, node, enabled, phase):
        _, rules = self.exec(node, ["sh", "-ec", firewall_script(enabled)])
        return self.record("partition" if enabled else "heal", node, phase=phase, rules=rules)

    def verify_isolation(self, node, phase):
        _, rules = self.exec(
            node,
            [
                "sh",
                "-ec",
                f"iptables -w 5 -C INPUT -j {FIREWALL_CHAIN}; iptables -w 5 -C OUTPUT -j {FIREWALL_CHAIN}; iptables -w 5 -S {FIREWALL_CHAIN}",
            ],
        )
        if "--dports 7000,7001 -j DROP" not in rules or "--sports 7000,7001 -j DROP" not in rules:
            raise RuntimeError("Incomplete internode isolation rules")
        peer = next(n for n, c in self.containers.items() if n != node and self.running(n))
        blocked_out = self.peer_tcp(node, peer) != 0
        blocked_in = self.peer_tcp(peer, node) != 0
        with socket.create_connection((self.addresses[node], 9042), timeout=3):
            pass
        if not blocked_out or not blocked_in:
            raise RuntimeError("Internode traffic remains reachable")
        return self.record(
            "verified_isolation",
            node,
            phase=phase,
            rules=rules,
            peer=peer,
            blocked_out=blocked_out,
            blocked_in=blocked_in,
            cql_tcp_reachable=True,
        )

    def running(self, node):
        self.containers[node].reload()
        return self.containers[node].status == "running"

    def stop(self, node):
        self.containers[node].stop(timeout=15)
        if self.running(node):
            raise RuntimeError("Node did not stop")
        return self.record("stop", node, status="stopped")

    def restore(self):
        for n, c in self.containers.items():
            if not self.running(n):
                c.start()
                self.record("start", n)
        for n in NAMES:
            self.set_isolated(n, False, "cleanup")

    def healthy(self, timeout=240):
        end = time.monotonic() + timeout
        last = ""
        while time.monotonic() < end:
            try:
                _, last = self.exec("N1", ["nodetool", "status"])
                if sum(line.startswith("UN ") for line in last.splitlines()) == 3:
                    for ip in self.addresses.values():
                        with socket.create_connection((ip, 9042), timeout=2):
                            pass
                    self.record("healthy_ring", "N1", status=last)
                    return
            except Exception as exc:
                last = repr(exc)
            time.sleep(3)
        raise RuntimeError(f"Cluster did not recover: {last}")

    def settle_views(self, expected_down, timeout=90):
        """Wait for the stated membership precondition, never retry a workload."""
        end = time.monotonic() + timeout
        last = {}
        while time.monotonic() < end:
            valid = True
            for observer, down in expected_down.items():
                _, output = self.exec(observer, ["nodetool", "status"])
                last[observer] = output
                states = {
                    line.split()[1]: line.split()[0]
                    for line in output.splitlines()
                    if line.startswith(("UN ", "DN "))
                }
                for target in NAMES:
                    expected = "DN" if target in down else "UN"
                    if states.get(self.addresses[target]) != expected:
                        valid = False
            if valid:
                return self.record(
                    "verified_membership", None, expected_down=expected_down, views=last
                )
            time.sleep(3)
        raise RuntimeError(f"Failure detector did not reach the stated precondition: {last}")

    def preflight(self):
        self.restore()
        self.healthy()
        for node in ("N1", "N3"):
            peer = "N2"
            if self.peer_tcp(node, peer) != 0 or self.peer_tcp(peer, node) != 0:
                raise RuntimeError("Internode TCP failed before injecting fault")
        self.record("preflight", None, all_paths_reachable=True)



class Trial:
    def __init__(self, case, executor):
        self.case = case
        self.db = executor
        self.history = []
        self.setup = []
        self.result = None
        self.x = case["trial_id"] + ":x"
        self.y = case["trial_id"] + ":y"

    def operation(self, op, phase="workload", **step):
        step = {"op": op, **step}
        if op == "write":
            step["timestamp_us"] = time.time_ns() // 1000
        e = self.db.execute(len(self.history), step)
        e.raw["phase"] = phase
        self.history.append(e)
        if e.status == "ok" and op in {"write", "read"}:
            expected = self.db.config.node_contact_points[e.node][0]
            if e.raw.get("coordinator") != expected:
                raise RuntimeError(f"Coordinator mismatch: expected {expected}, observed {e.raw}")
        return e

    def prepare(self):
        for key in (self.x, self.y):
            s = {
                "op": "write",
                "node": "N1",
                "client": "setup",
                "key": key,
                "version": 0,
                "write_id": key + ":initial",
                "consistency": "ALL",
                "timestamp_us": time.time_ns() // 1000,
            }
            e = self.db.execute(0, s)
            if e.status != "ok":
                raise RuntimeError(f"Initial ALL write failed: {asdict(e)}")
            self.setup.append(asdict(e))
        for node in NAMES:
            e = self.db.execute(
                0,
                {
                    "op": "read",
                    "node": node,
                    "client": "setup",
                    "key": self.x,
                    "consistency": "ONE",
                },
            )
            if e.status != "ok" or e.version != 0 or e.write_id != self.x + ":initial":
                raise RuntimeError(f"Initial data verification failed: {asdict(e)}")
            self.setup.append(asdict(e))

    def workload(self):
        prop = self.case["property"]
        scenario = self.case["scenario"]
        cl = self.case["consistency"]
        read_node = "N2" if scenario == "node_stop" else "N3"
        cause_node = "N2" if scenario == "node_stop" else "N3"
        common = {"consistency": cl}
        if prop in PROPERTIES[:2]:
            w = self.operation(
                "write",
                node="N1",
                client="A" if prop == PROPERTIES[0] else "B",
                key=self.x,
                version=1,
                write_id=self.x + ":new",
                **common,
            )
            if w.status == "ok":
                if prop == PROPERTIES[1]:
                    first = self.operation("read", node="N1", client="A", key=self.x, **common)
                    if first.status != "ok" or first.version != 1:
                        self.result = CheckResult(
                            prop,
                            "INCONCLUSIVE",
                            "MR initial fresh read was not obtained.",
                        )
                        return
                self.operation("read", node=read_node, client="A", key=self.x, **common)
            self.result = check(prop, self.history)
            return
        w = self.operation(
            "write",
            node=cause_node,
            client="A" if prop == PROPERTIES[2] else "B",
            key=self.x,
            version=1,
            write_id=self.x + ":cause",
            seq=1,
            **common,
        )
        if w.status != "ok":
            self.result = check(prop, self.history)
            return
        cause = w
        if prop == PROPERTIES[3]:
            cause = self.operation("read", node=cause_node, client="A", key=self.x, **common)
            if cause.status != "ok" or cause.version != 1 or cause.write_id != w.write_id:
                self.result = CheckResult(
                    prop, "INCONCLUSIVE", "Writer did not observe the intended cause."
                )
                return
        effect = self.operation(
            "write",
            node="N1",
            client="A",
            key=self.y,
            version=1,
            write_id=self.y + ":effect",
            seq=2,
            depends_on={
                "key": self.x,
                "min_version": cause.version,
                "write_id": cause.write_id,
            },
            **common,
        )
        if effect.status != "ok":
            self.result = check(prop, self.history)

    def probe(self, control_id):
        effect = self.operation(
            "read",
            phase="probe",
            node="N1",
            client="observer",
            key=self.y,
            consistency="ONE",
        )
        cause = self.operation(
            "read",
            phase="probe",
            node="N1",
            client="observer",
            key=self.x,
            consistency="ONE",
        )
        e = Observation(
            len(self.history),
            "dependency_probe",
            status="ok" if effect.status == cause.status == "ok" else "error",
            node="N1",
            key=self.y,
            version=effect.version,
            write_id=effect.write_id,
            raw={
                "phase": "probe",
                "local_observation": True,
                "control_id": control_id,
                "cause_key": self.x,
                "cause_version": cause.version,
                "cause_write_id": cause.write_id,
                "effect_read_index": effect.index,
                "cause_read_index": cause.index,
            },
        )
        self.history.append(e)
        self.result = check(self.case["property"], self.history)

    def export(self):
        return {
            **self.case,
            "setup": self.setup,
            "history": [asdict(e) for e in self.history],
            "result": asdict(self.result),
            "workload_requests": sum(
                e.op in {"read", "write"} and e.raw.get("phase") == "workload" for e in self.history
            ),
            "failed_workload_requests": sum(
                e.status != "ok" and e.raw.get("phase") == "workload" for e in self.history
            ),
        }


def summarize(records):
    groups = defaultdict(list)
    for r in records:
        groups[(r["scenario"], r["consistency"], r["property"])].append(r)
    result = []
    for (s, c, p), rows in groups.items():
        counts = Counter(r["result"]["status"] for r in rows)
        result.append(
            {
                "scenario": s,
                "consistency": c,
                "property": p,
                "trials": len(rows),
                **{k: counts[k] for k in ["PASS", "VIOLATION", "INCONCLUSIVE"]},
                "workload_requests": sum(r["workload_requests"] for r in rows),
                "failed_workload_requests": sum(r["failed_workload_requests"] for r in rows),
            }
        )
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--seed", type=int, default=5208)
    args = ap.parse_args()
    if args.repeats < 1:
        raise ValueError("repeats must be positive")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
    out = args.output or Path("results") / run_id
    out.mkdir(parents=True, exist_ok=False)
    save(
        out / "plan.json",
        {
            "run_id": run_id,
            "written_before_workloads": True,
            "repeats_per_cell": args.repeats,
            "seed": args.seed,
            "fault_episodes_per_scenario": 1,
            "hypotheses": [
                {
                    "scenario": s,
                    "consistency": c,
                    "property": p,
                    "prediction": prediction(s, c, p),
                }
                for s in SCENARIOS
                for c in LEVELS
                for p in PROPERTIES
            ],
            "scope": "RYW/MR: controlled version reads. MW/WFR: immutable predecessor visibility at isolated local probe, not complete internal order proof.",
            "probe_consistency": "ONE, separately recorded from workload CL; probe isolation begins after workload.",
        },
    )
    ctrl = LabControl(out)
    db = None
    records = []
    stream = (out / "histories.jsonl").open("w")
    try:
        ctrl.preflight()
        config = CassandraConfig(
            keyspace="lab_" + uuid.uuid4().hex[:12],
            contact_points=(ctrl.addresses["N1"],),
            node_contact_points={n: (ip,) for n, ip in ctrl.addresses.items()},
            node_ports={n: 9042 for n in NAMES},
        )
        db = CassandraExecutor(config)
        versions = {
            n: db._session_for_step({"node": n})
            .execute("SELECT release_version FROM system.local")
            .one()
            .release_version
            for n in NAMES
        }
        save(
            out / "environment.json",
            {
                "nodes": ctrl.addresses,
                "config": asdict(config),
                "cassandra_versions": versions,
                "python": platform.python_version(),
                "driver": version("cassandra-driver"),
                "docker_sdk": version("docker"),
            },
        )
        for scenario in SCENARIOS:
            print(f"{run_id}: preparing {scenario}", flush=True)
            ctrl.healthy()
            ctrl.settle_views({n: [] for n in NAMES})
            # A restarted node may remain down in an old driver pool. Establish
            # fresh pinned sessions between scenarios, before data preparation.
            db.close()
            db = CassandraExecutor(config)
            for node in NAMES:
                db._session_for_step({"node": node}).execute(
                    "SELECT release_version FROM system.local"
                )
            cases = [
                {
                    "trial_id": f"{run_id}:{scenario}:{cl}:{prop}:{i}",
                    "scenario": scenario,
                    "consistency": cl,
                    "property": prop,
                    "repetition": i,
                }
                for cl in LEVELS
                for prop in PROPERTIES
                for i in range(args.repeats)
            ]
            random.Random(args.seed + SCENARIOS.index(scenario)).shuffle(cases)
            trials = [Trial(case, db) for case in cases]
            for t in trials:
                t.prepare()
            if scenario == "node_stop":
                ctrl.stop("N3")
            elif scenario == "partition":
                ctrl.set_isolated("N3", True, "workload")
                ctrl.verify_isolation("N3", "workload")
            # Let membership detection settle; this is one sustained fault episode.
            if scenario == "node_stop":
                ctrl.settle_views({"N1": ["N3"], "N2": ["N3"]})
            elif scenario == "partition":
                ctrl.settle_views({"N1": ["N3"], "N2": ["N3"], "N3": ["N1", "N2"]})
            pending = []
            for i, t in enumerate(trials):
                t.workload()
                if t.result is None:
                    pending.append(t)
                else:
                    r = t.export()
                    records.append(r)
                    stream.write(json.dumps(r) + "\n")
                    stream.flush()
                if (i + 1) % 12 == 0:
                    print(f"{scenario}: workload {i + 1}/{len(trials)}", flush=True)
            if pending:
                ctrl.set_isolated("N1", True, "measurement")
                proof = ctrl.verify_isolation("N1", "measurement")
                ctrl.settle_views({"N1": ["N2", "N3"]})
                for t in pending:
                    t.probe(proof["control_id"])
                    r = t.export()
                    records.append(r)
                    stream.write(json.dumps(r) + "\n")
                    stream.flush()
                ctrl.set_isolated("N1", False, "measurement_end")
            ctrl.restore()
            ctrl.healthy()
            save(out / "summary.json", summarize(records))
            print(f"{scenario}: recorded {len(trials)} trial histories", flush=True)
        save(
            out / "completion.json",
            {
                "status": "complete",
                "histories": len(records),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        print(json.dumps(summarize(records), indent=2), flush=True)
    except BaseException as exc:
        save(
            out / "completion.json",
            {"status": "incomplete", "error": repr(exc), "histories": len(records)},
        )
        raise
    finally:
        try:
            ctrl.restore()
            ctrl.healthy()
        finally:
            if db:
                db.close()
            stream.close()
            ctrl.log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
