from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .checker import check
from .executor import Executor
from .model import Observation, CheckResult


def load_trajectory(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if "name" not in data:
        raise ValueError(f"{p}: missing 'name'")
    if "property" not in data:
        raise ValueError(f"{p}: missing 'property'")
    if not isinstance(data.get("steps"), list) or not data["steps"]:
        raise ValueError(f"{p}: 'steps' must be a non-empty list")

    for i, step in enumerate(data["steps"]):
        if not isinstance(step, dict) or "op" not in step:
            raise ValueError(f"{p}: step {i} must be an object containing 'op'")

    return data


def run_trajectory(trajectory: dict[str, Any], executor: Executor) -> tuple[list[Observation], CheckResult]:
    history = [
        executor.execute(index=i, step=step)
        for i, step in enumerate(trajectory["steps"])
    ]
    result = check(trajectory["property"], history)
    return history, result
