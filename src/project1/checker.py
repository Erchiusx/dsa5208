"""Finite-history checks. PASS means no violation in the completed observations.

Versions must encode a controlled single-writer order. Dependency probes use
immutable markers and a verified replica-local observation; they do not prove
all internal execution orders from the absence of a witness.
"""

from __future__ import annotations

from .model import CheckResult, Observation


def check(property_name: str, history: list[Observation]) -> CheckResult:
    functions = {
        "read_your_writes": check_read_your_writes,
        "monotonic_reads": check_monotonic_reads,
        "monotonic_writes": check_monotonic_writes,
        "writes_follow_reads": check_writes_follow_reads,
    }
    if property_name not in functions:
        raise ValueError(f"unknown property: {property_name}")
    return functions[property_name](history)


def _finish(prop, complete, history, reason):
    incomplete = any(
        e.status != "ok"
        for e in history
        if e.op in {"write", "read", "dependency_probe", "partition", "stop"}
    )
    if not complete or incomplete:
        return CheckResult(
            prop,
            "INCONCLUSIVE",
            "Required observations or successful prerequisites are missing.",
        )
    return CheckResult(
        prop,
        "PASS",
        reason + " This is a finite-history result, not a universal guarantee.",
    )


def check_read_your_writes(history):
    latest = {}
    pairs = 0
    for e in history:
        if e.status != "ok" or e.client is None or e.key is None or e.version is None:
            continue
        ck = (e.client, e.key)
        if e.op == "write":
            if ck not in latest or e.version > latest[ck].version:
                latest[ck] = e
        elif e.op == "read" and ck in latest:
            pairs += 1
            w = latest[ck]
            if e.version < w.version:
                return CheckResult(
                    "read_your_writes",
                    "VIOLATION",
                    f"{e.client} wrote {e.key}=v{w.version}, then read v{e.version}.",
                    [w.index, e.index],
                )
    return _finish(
        "read_your_writes",
        pairs > 0,
        history,
        "No stale successful post-write read observed.",
    )


def check_monotonic_reads(history):
    latest = {}
    pairs = 0
    for e in history:
        if (
            e.op != "read"
            or e.status != "ok"
            or e.client is None
            or e.key is None
            or e.version is None
        ):
            continue
        ck = (e.client, e.key)
        if ck in latest:
            pairs += 1
            prev = latest[ck]
            if e.version < prev.version:
                return CheckResult(
                    "monotonic_reads",
                    "VIOLATION",
                    f"{e.client} read {e.key}=v{prev.version}, then v{e.version}.",
                    [prev.index, e.index],
                )
        latest[ck] = e
    return _finish("monotonic_reads", pairs > 0, history, "No backward read observed.")


def _dependencies(history, prop):
    """Only accept dependencies justified by this writer's earlier operations."""
    candidates = []
    for i, e in enumerate(history):
        if e.op != "write" or e.status != "ok" or not e.depends_on:
            continue
        dep = e.depends_on
        prior_op = "write" if prop == "monotonic_writes" else "read"
        matches = [
            p
            for p in history[:i]
            if p.op == prior_op
            and p.status == "ok"
            and p.client == e.client
            and p.key == dep.get("key")
            and p.version is not None
            and p.version == dep.get("min_version")
            and (not dep.get("write_id") or dep["write_id"] == p.write_id)
        ]
        if matches:
            candidates.append((e, matches[-1]))
    return candidates


def _check_probes(history, prop, candidates):
    """Detect missing predecessors with an isolated, same-replica marker probe."""
    covered = set()
    for e in history:
        if e.op != "dependency_probe" or e.status != "ok":
            continue
        r = e.raw
        if not e.node or not r.get("local_observation") or not r.get("control_id"):
            continue
        for effect, cause in candidates:
            if e.index <= effect.index or e.key != effect.key or e.version != effect.version:
                continue
            if not effect.write_id or e.write_id != effect.write_id:
                continue
            if r.get("cause_key") != cause.key or r.get("cause_version") is None:
                continue
            if r["cause_version"] < cause.version:
                return CheckResult(
                    prop,
                    "VIOLATION",
                    f"Replica {e.node} exposed {effect.write_id} but lacked its predecessor {cause.write_id or cause.key}.",
                    [cause.index, effect.index, e.index],
                )
            if r.get("cause_write_id") != cause.write_id:
                continue  # equal/larger application version cannot establish write identity
            covered.add(effect.index)
    return _finish(
        prop,
        bool(candidates) and len(covered) == len(candidates),
        history,
        "All observed immutable effects had their required predecessors in the local probes.",
    )


def check_monotonic_writes(history):
    candidates = _dependencies(history, "monotonic_writes")
    if any(e.op == "dependency_probe" for e in history):
        return _check_probes(history, "monotonic_writes", candidates)
    # An application-order list is meaningful only for an explicitly synthetic
    # fixture. The Cassandra seq-sorted table is no longer accepted as evidence.
    writes = {
        e.write_id: e
        for e in history
        if e.op == "write" and e.status == "ok" and e.write_id and e.seq is not None
    }
    complete = False
    for audit in history:
        if (
            audit.op != "audit_order"
            or audit.status != "ok"
            or audit.raw.get("evidence_source") != "synthetic_application_order"
        ):
            continue
        order = audit.order or []
        if len(writes) < 2 or not set(writes).issubset(order):
            continue
        last = {}
        for wid in order:
            if wid not in writes:
                continue
            w = writes[wid]
            if w.client in last and w.seq < last[w.client].seq:
                return CheckResult(
                    "monotonic_writes",
                    "VIOLATION",
                    "Synthetic application order reversed a client dependency.",
                    [last[w.client].index, w.index, audit.index],
                )
            last[w.client] = w
        complete = True
    return _finish(
        "monotonic_writes",
        complete,
        history,
        "Synthetic application order preserved the observed writes.",
    )


def check_writes_follow_reads(history):
    candidates = _dependencies(history, "writes_follow_reads")
    if any(e.op == "dependency_probe" for e in history):
        return _check_probes(history, "writes_follow_reads", candidates)
    # Legacy JSON fixtures describe synthetic local reads. Real DB claims must
    # use a locality-verified dependency_probe, not coordinator labels alone.
    covered = set()
    for effect, cause in candidates:
        for i, seen in enumerate(history):
            if (
                seen.index <= effect.index
                or seen.op != "read"
                or seen.status != "ok"
                or "mock" not in seen.raw
            ):
                continue
            if seen.key != effect.key or seen.version != effect.version:
                continue
            for read in history[i + 1 :]:
                if read.op != "read" or read.status != "ok" or "mock" not in read.raw:
                    continue
                if (
                    read.client != seen.client
                    or read.node != seen.node
                    or read.key != cause.key
                    or read.version is None
                ):
                    continue
                if read.version < cause.version:
                    return CheckResult(
                        "writes_follow_reads",
                        "VIOLATION",
                        "Synthetic observer saw effect without its observed cause.",
                        [cause.index, effect.index, seen.index, read.index],
                    )
                covered.add(effect.index)
    return _finish(
        "writes_follow_reads",
        bool(candidates) and len(covered) == len(candidates),
        history,
        "Synthetic observations preserved the observed read-to-write dependency.",
    )
