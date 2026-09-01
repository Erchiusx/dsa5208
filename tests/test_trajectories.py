from pathlib import Path

import pytest

from project1.mock_executor import MockExecutor
from project1.runner import load_trajectory, run_trajectory


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("ryw_partition_violation.json", "VIOLATION"),
        ("ryw_pass.json", "PASS"),
        ("monotonic_reads_violation.json", "VIOLATION"),
        ("monotonic_writes_violation.json", "VIOLATION"),
        ("writes_follow_reads_violation.json", "VIOLATION"),
    ],
)
def test_manual_trajectories(filename: str, expected: str) -> None:
    trajectory = load_trajectory(ROOT / "trajectories" / filename)
    _, result = run_trajectory(trajectory, MockExecutor())
    assert result.status == expected
