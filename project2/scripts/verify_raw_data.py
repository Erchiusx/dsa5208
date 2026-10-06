#!/usr/bin/env python3
"""Validate the annual raw-data inventory against data.gov.sg metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_DIR / "data" / "raw"
METADATA = PROJECT_DIR / "data" / "metadata" / "source-collection-2279.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", type=Path)
    args = parser.parse_args()

    metadata = json.loads(METADATA.read_text())
    datasets = metadata["data"]["datasetMetadata"]
    expected = {
        item["coverageStart"][:4]: {"dataset_id": item["datasetId"], "bytes": item["datasetSize"]}
        for item in datasets
        if "2017" <= item["coverageStart"][:4] <= "2024"
    }

    inventory: dict[str, object] = {
        "source_collection": "https://data.gov.sg/collections/2279/view",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": {},
    }
    failures: list[str] = []
    for year, source in sorted(expected.items()):
        path = RAW_DIR / f"rainfall_{year}.csv"
        if not path.is_file():
            failures.append(f"{year}: missing {path.name}")
            continue
        actual_bytes = path.stat().st_size
        entry = {**source, "bytes_downloaded": actual_bytes, "sha256": sha256(path)}
        inventory["files"][year] = entry  # type: ignore[index]
        print(f"OK {year}: {actual_bytes:,} exported CSV bytes")

    if args.write_manifest:
        args.write_manifest.parent.mkdir(parents=True, exist_ok=True)
        args.write_manifest.write_text(json.dumps(inventory, indent=2) + "\n")
        print(f"Wrote {args.write_manifest}")
    if failures:
        raise SystemExit("Raw data validation failed:\n" + "\n".join(failures))


if __name__ == "__main__":
    main()
