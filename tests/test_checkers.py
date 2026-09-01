from project1.checker import (
    check_monotonic_reads,
    check_read_your_writes,
    check_writes_follow_reads,
)
from project1.model import Observation


def test_ryw_newer_value_is_allowed() -> None:
    history = [
        Observation(0, "write", client="A", key="x", version=10),
        Observation(1, "read", client="A", key="x", version=11),
    ]
    assert check_read_your_writes(history).status == "PASS"


def test_failed_write_does_not_create_ryw_requirement() -> None:
    history = [
        Observation(0, "write", status="timeout", client="A", key="x", version=10),
        Observation(1, "read", client="A", key="x", version=0),
    ]
    assert check_read_your_writes(history).status == "INCONCLUSIVE"


def test_monotonic_reads_detects_backward_read() -> None:
    history = [
        Observation(0, "read", client="A", key="x", version=5),
        Observation(1, "read", client="A", key="x", version=4),
    ]
    assert check_monotonic_reads(history).status == "VIOLATION"


def test_wfr_passes_when_cause_is_visible() -> None:
    history = [
        Observation(
            0,
            "write",
            client="A",
            key="y",
            version=1,
            depends_on={"key": "x", "min_version": 1},
        ),
        Observation(1, "read", client="C", key="y", version=1),
        Observation(2, "read", client="C", key="x", version=1),
    ]
    assert check_writes_follow_reads(history).status == "PASS"
