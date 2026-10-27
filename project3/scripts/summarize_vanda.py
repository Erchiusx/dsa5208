#!/usr/bin/env python3
"""Extract per-trial search results from the preserved Vanda CPU logs."""

import csv
import re
import sys
from pathlib import Path


FIELDS = (
    "job_id", "trial", "hosts", "backend", "depth", "ranks", "threads",
    "split_depth", "binding", "score", "move", "nodes", "leaves",
    "cutoffs", "seconds", "frontier_nodes", "source_sha256",
)


def attributes(line):
    return dict(re.findall(r"(?:^|\s)([a-z_]+)=([^\s]+)", line))


def rows(path):
    header = {}
    hosts = []
    in_hosts = False
    source_sha = ""
    trial = 1
    for line in path.read_text().splitlines():
        if line.startswith("job="):
            header = attributes(line)
        elif line == "nodes:":
            in_hosts = True
        elif in_hosts:
            if line.startswith("GCC runtime"):
                in_hosts = False
            elif line.strip():
                hosts.append(line.strip())
        elif line.endswith("  src/main.cpp"):
            source_sha = line.split()[0]
        elif line.startswith("trial="):
            trial = int(attributes(line)["trial"])
        elif line.startswith("backend="):
            result = attributes(line)
            row = {field: result.get(field, "") for field in FIELDS}
            row.update(
                job_id=path.stem,
                trial=trial,
                hosts=";".join(hosts),
                binding=header.get("binding", "default"),
                source_sha256=source_sha,
            )
            yield row


def main():
    raw_dir = Path(__file__).resolve().parent.parent / "experiments" / "raw"
    writer = csv.DictWriter(sys.stdout, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    for path in sorted(raw_dir.glob("[0-9]*.txt")):
        for row in rows(path):
            writer.writerow(row)


if __name__ == "__main__":
    main()
