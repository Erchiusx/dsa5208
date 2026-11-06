#!/usr/bin/env python3
"""Summarize archived CPU runs; never silently use incomplete repetitions."""
import csv
import json
from pathlib import Path
from collections import defaultdict
from statistics import median

root = Path(__file__).resolve().parents[1] / 'experiments/multiposition'
paths = sorted((root / 'raw').glob('*/runs.jsonl'))
rows = [dict(json.loads(line), log=str(p.relative_to(root))) for p in paths for line in p.read_text().splitlines()]
fields = sorted(set().union(*(r.keys() for r in rows)))
with (root / 'runs.csv').open('w', newline='') as out:
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
references = defaultdict(set)
for row in rows:
    if row['phase'] != 'pilot' and row.get('backend') == 'serial' and row['exit_code'] == 0:
        references[(row['position'], row['depth'])].add(row['score'])
groups = defaultdict(list)
failures = []
for row in rows:
    if row['phase'] == 'pilot':
        continue
    if row['exit_code'] != 0:
        failures.append(row)
        continue
    key = (row['position'], row['depth'], row['backend'], row['ranks'], row['threads'], row['split_depth'], row['job'])
    groups[key].append(row)
summary = []
for key, runs in sorted(groups.items()):
    position, depth, backend, ranks, threads, split, job = key
    scores = set(r['score'] for r in runs)
    reference = references[(position, depth)]
    status = 'PASS' if len(reference) == 1 and scores == reference else 'CHECK'
    if len(runs) != 3 or len(set(r['trial'] for r in runs)) != 3:
        status = 'INCOMPLETE'
    times = [float(r['seconds']) for r in runs]
    summary.append(dict(position=position, depth=depth, backend=backend, ranks=ranks,
                        threads=threads, split=split, job=job, trials=len(runs), status=status,
                        median_seconds=median(times) if status == 'PASS' else '',
                        min_seconds=min(times), max_seconds=max(times), score=','.join(sorted(scores))))
with (root / 'summary.csv').open('w', newline='') as out:
    writer = csv.DictWriter(out, fieldnames=list(summary[0]))
    writer.writeheader()
    writer.writerows(summary)
scaling = []
for row in summary:
    if row['status'] != 'PASS' or row['backend'] != 'mpi' or row['threads'] != '72' or row['split'] != '3':
        continue
    matching = [r for r in summary if r['position'] == row['position'] and r['depth'] == row['depth'] and r['status'] == 'PASS']
    serial = next(r for r in matching if r['backend'] == 'serial')
    task = next(r for r in matching if r['backend'] == 'mpi' and r['ranks'] == '1' and r['threads'] == '1' and r['split'] == '3')
    cores = int(row['ranks']) * int(row['threads'])
    seconds = row['median_seconds']
    scaling.append(dict(position=row['position'], depth=row['depth'], cores=cores,
                        job=row['job'], seconds=seconds,
                        serial_seconds=serial['median_seconds'], task_one_worker_seconds=task['median_seconds'],
                        speedup_vs_serial=serial['median_seconds'] / seconds,
                        speedup_vs_task=task['median_seconds'] / seconds,
                        efficiency_vs_task=task['median_seconds'] / seconds / cores))
with (root / 'strong_scaling.csv').open('w', newline='') as out:
    writer = csv.DictWriter(out, fieldnames=list(scaling[0]))
    writer.writeheader()
    writer.writerows(sorted(scaling, key=lambda r: (r['position'], r['cores'])))
text = ['# CPU multi-position results', '', 'Archive updated 6 November 2026. All 24 planned strong-scaling configurations completed three successful trials. No GPU results.', '',
        'PASS requires three distinct measured trials agreeing with the corresponding serial score.',
        'INCOMPLETE groups have no formal median. Failed/time-limited runs remain in runs.csv.', '',
        '| Position | Depth | Backend | Ranks × threads | Split | Trials | Median (s) | Status |',
        '|---|---:|---|---|---:|---:|---:|---|']
for r in summary:
    m = f"{r['median_seconds']:.6f}" if r['median_seconds'] != '' else '—'
    text.append(f"| {r['position']} | {r['depth']} | {r['backend']} | {r['ranks']} × {r['threads']} | {r['split']} | {r['trials']} | {m} | {r['status']} |")
text += ['', f'Failed/time-limited recorded runs: {len(failures)}.', '',
         'Timing is the executable search region; runs.csv separately retains launcher walltime.',
         'Hardware/software provenance is preserved in the adjacent session.log files.']
(root / 'RESULTS.md').write_text('\n'.join(text) + '\n')
print('runs', len(rows), 'groups', len(groups), 'failed', len(failures), 'complete pass', sum(r['status']=='PASS' for r in summary))
