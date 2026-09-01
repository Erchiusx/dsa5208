from __future__ import annotations

import argparse
import json

from .mock_executor import MockExecutor
from .runner import load_trajectory, run_trajectory


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trajectory", help="path to trajectory JSON")
    args = parser.parse_args()

    trajectory = load_trajectory(args.trajectory)
    history, result = run_trajectory(trajectory, MockExecutor())

    print(f"trajectory: {trajectory['name']}")
    print(f"property:   {result.property_name}")
    print(f"status:     {result.status}")
    print(f"reason:     {result.reason}")
    if result.witness:
        print(f"witness:    {result.witness}")

    print("\nhistory:")
    for ev in history:
        print(json.dumps({
            "index": ev.index,
            "op": ev.op,
            "status": ev.status,
            "client": ev.client,
            "node": ev.node,
            "key": ev.key,
            "version": ev.version,
            "write_id": ev.write_id,
            "seq": ev.seq,
            "depends_on": ev.depends_on,
            "order": ev.order,
        }, ensure_ascii=False))

    return 1 if result.status == "VIOLATION" else 0


if __name__ == "__main__":
    raise SystemExit(main())
