from __future__ import annotations

from collections import defaultdict

from .model import Observation, CheckResult


def check(property_name: str, history: list[Observation]) -> CheckResult:
    dispatch = {
        "read_your_writes": check_read_your_writes,
        "monotonic_reads": check_monotonic_reads,
        "monotonic_writes": check_monotonic_writes,
        "writes_follow_reads": check_writes_follow_reads,
    }
    try:
        fn = dispatch[property_name]
    except KeyError as exc:
        raise ValueError(f"unknown property: {property_name}") from exc
    return fn(history)


def check_read_your_writes(history: list[Observation]) -> CheckResult:
    latest_write: dict[tuple[str, str], tuple[int, int]] = {}
    saw_relevant_pair = False

    for ev in history:
        if ev.status != "ok" or ev.client is None or ev.key is None:
            continue

        ck = (ev.client, ev.key)

        if ev.op == "write" and ev.version is not None:
            prev = latest_write.get(ck)
            if prev is None or ev.version > prev[0]:
                latest_write[ck] = (ev.version, ev.index)

        elif ev.op == "read" and ev.version is not None and ck in latest_write:
            saw_relevant_pair = True
            required, write_idx = latest_write[ck]
            if ev.version < required:
                return CheckResult(
                    "read_your_writes",
                    "VIOLATION",
                    f"{ev.client} wrote {ev.key}=v{required} successfully "
                    f"but later read v{ev.version}.",
                    [write_idx, ev.index],
                )

    if not saw_relevant_pair:
        return CheckResult(
            "read_your_writes",
            "INCONCLUSIVE",
            "No successful write followed by a successful read from the same client/key.",
        )

    return CheckResult(
        "read_your_writes",
        "PASS",
        "Every successful post-write read was at least as new as the client's latest successful write.",
    )


def check_monotonic_reads(history: list[Observation]) -> CheckResult:
    latest_read: dict[tuple[str, str], tuple[int, int]] = {}
    saw_pair = False

    for ev in history:
        if (
            ev.op != "read"
            or ev.status != "ok"
            or ev.client is None
            or ev.key is None
            or ev.version is None
        ):
            continue

        ck = (ev.client, ev.key)
        if ck in latest_read:
            saw_pair = True
            prev_version, prev_idx = latest_read[ck]
            if ev.version < prev_version:
                return CheckResult(
                    "monotonic_reads",
                    "VIOLATION",
                    f"{ev.client} read {ev.key}=v{prev_version} and later went backwards to v{ev.version}.",
                    [prev_idx, ev.index],
                )

        prev = latest_read.get(ck)
        if prev is None or ev.version > prev[0]:
            latest_read[ck] = (ev.version, ev.index)

    if not saw_pair:
        return CheckResult(
            "monotonic_reads",
            "INCONCLUSIVE",
            "No client/key had two successful reads.",
        )

    return CheckResult(
        "monotonic_reads",
        "PASS",
        "No client observed a version older than one it had already read.",
    )


def check_monotonic_writes(history: list[Observation]) -> CheckResult:
    seq_by_write_id: dict[str, tuple[str, int, int]] = {}

    for ev in history:
        if (
            ev.op == "write"
            and ev.status == "ok"
            and ev.client is not None
            and ev.write_id is not None
            and ev.seq is not None
        ):
            seq_by_write_id[ev.write_id] = (ev.client, ev.seq, ev.index)

    audits = [ev for ev in history if ev.op == "audit_order" and ev.status == "ok" and ev.order]

    if not seq_by_write_id or not audits:
        return CheckResult(
            "monotonic_writes",
            "INCONCLUSIVE",
            "Need successful writes with write_id/seq plus at least one audit_order observation.",
        )

    for audit in audits:
        last_seq = defaultdict(lambda: -1)
        last_idx: dict[str, int] = {}

        for write_id in audit.order or []:
            meta = seq_by_write_id.get(write_id)
            if meta is None:
                continue

            client, seq, issued_idx = meta
            if seq < last_seq[client]:
                return CheckResult(
                    "monotonic_writes",
                    "VIOLATION",
                    f"Backend audit order applies {client} write seq={seq} after seq={last_seq[client]}.",
                    [last_idx[client], issued_idx, audit.index],
                )

            last_seq[client] = seq
            last_idx[client] = issued_idx

    return CheckResult(
        "monotonic_writes",
        "PASS",
        "All audited per-client write sequences were monotonic.",
    )


def check_writes_follow_reads(history: list[Observation]) -> CheckResult:
    # Map effect value (key, version) -> dependency (cause_key, minimum cause version, writer event index)
    dependencies: dict[tuple[str, int], tuple[str, int, int]] = {}

    for ev in history:
        if (
            ev.op == "write"
            and ev.status == "ok"
            and ev.key is not None
            and ev.version is not None
            and ev.depends_on
        ):
            dep_key = ev.depends_on.get("key")
            dep_version = ev.depends_on.get("min_version")
            if dep_key is not None and dep_version is not None:
                dependencies[(ev.key, ev.version)] = (dep_key, int(dep_version), ev.index)

    if not dependencies:
        return CheckResult(
            "writes_follow_reads",
            "INCONCLUSIVE",
            "No successful dependency-carrying write was observed.",
        )

    # For each observer, remember which dependency becomes required once the effect is seen.
    required_by_observer: dict[str, dict[str, tuple[int, int]]] = defaultdict(dict)
    saw_effect = False

    for ev in history:
        if (
            ev.op != "read"
            or ev.status != "ok"
            or ev.client is None
            or ev.key is None
            or ev.version is None
        ):
            continue

        effect = dependencies.get((ev.key, ev.version))
        if effect is not None:
            dep_key, min_version, write_idx = effect
            current = required_by_observer[ev.client].get(dep_key)
            if current is None or min_version > current[0]:
                required_by_observer[ev.client][dep_key] = (min_version, write_idx)
            saw_effect = True
            continue

        requirement = required_by_observer[ev.client].get(ev.key)
        if requirement is not None:
            min_version, write_idx = requirement
            if ev.version < min_version:
                return CheckResult(
                    "writes_follow_reads",
                    "VIOLATION",
                    f"{ev.client} observed an effect that depends on {ev.key}>=v{min_version}, "
                    f"but then read {ev.key}=v{ev.version}.",
                    [write_idx, ev.index],
                )

    if not saw_effect:
        return CheckResult(
            "writes_follow_reads",
            "INCONCLUSIVE",
            "No observer read a dependency-carrying effect value.",
        )

    return CheckResult(
        "writes_follow_reads",
        "PASS",
        "No observer saw an effect and then observed its required cause below the dependency version.",
    )
