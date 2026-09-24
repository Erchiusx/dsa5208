from project1.checker import check_monotonic_writes, check_writes_follow_reads
from project1.model import Observation as O


def wfr_history(read_version=1):
    return [
        O(0, "read", client="A", key="x", version=read_version),
        O(
            1,
            "write",
            client="A",
            key="y",
            version=1,
            depends_on={"key": "x", "min_version": 1},
        ),
        O(2, "read", client="C", key="y", version=1),
    ]


def test_wfr_needs_cause_observation():
    assert check_writes_follow_reads(wfr_history()).status == "INCONCLUSIVE"


def test_wfr_dependency_must_have_been_observed():
    assert (
        check_writes_follow_reads(
            wfr_history(0) + [O(3, "read", client="C", key="x", version=0)]
        ).status
        == "INCONCLUSIVE"
    )


def test_mw_incomplete_audit_is_not_positive_evidence():
    h = [
        O(0, "write", client="A", write_id="A1", seq=1),
        O(1, "write", client="A", write_id="A2", seq=2),
        O(2, "audit_order", order=["A2"]),
    ]
    assert check_monotonic_writes(h).status == "INCONCLUSIVE"


def dependency_history(prop="mw", cause_version=1, local=True):
    cause = O(
        0,
        "write" if prop == "mw" else "read",
        client="A",
        key="x",
        version=1,
        write_id="x1",
        seq=1,
    )
    effect = O(
        1,
        "write",
        client="A",
        key="y",
        version=1,
        write_id="y1",
        seq=2,
        depends_on={"key": "x", "min_version": 1, "write_id": "x1"},
    )
    probe = O(
        2,
        "dependency_probe",
        node="N1",
        key="y",
        version=1,
        write_id="y1",
        raw={
            "local_observation": local,
            "control_id": 1,
            "cause_key": "x",
            "cause_version": cause_version,
            "cause_write_id": "x1" if cause_version else "x0",
        },
    )
    return [cause, effect, probe]


def test_mw_local_missing_predecessor_is_a_witness():
    assert check_monotonic_writes(dependency_history(cause_version=0)).status == "VIOLATION"


def test_mw_complete_local_dependency_is_observed_pass():
    assert check_monotonic_writes(dependency_history()).status == "PASS"


def test_probe_without_locality_is_inconclusive():
    assert (
        check_monotonic_writes(dependency_history(local=False, cause_version=0)).status
        == "INCONCLUSIVE"
    )


def test_wfr_validated_cause_and_local_probe():
    assert check_writes_follow_reads(dependency_history("wfr")).status == "PASS"
    assert (
        check_writes_follow_reads(dependency_history("wfr", cause_version=0)).status == "VIOLATION"
    )


def test_wfr_wrong_write_identity_cannot_establish_dependency():
    h = dependency_history("wfr")
    h[1].depends_on["write_id"] = "unseen"
    assert check_writes_follow_reads(h).status == "INCONCLUSIVE"


def test_same_version_wrong_cause_identity_is_inconclusive():
    h = dependency_history()
    h[-1].raw["cause_write_id"] = "other"
    assert check_monotonic_writes(h).status == "INCONCLUSIVE"


def test_fault_rules_cover_both_directions_and_preserve_client_port():
    from project1.failure_control import firewall_script

    s = firewall_script(True)
    assert "--dports 7000,7001" in s and "--sports 7000,7001" in s
    assert "INPUT" in s and "OUTPUT" in s
    assert "9042" not in s and "network disconnect" not in s


def test_synthetic_fixture_is_rejected_before_database_connection():
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "project1.cli",
            "--executor",
            "cassandra",
            "trajectories/monotonic_reads_violation.json",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "synthetic checker fixture" in result.stderr
