#!/usr/bin/env python3
"""Vanda compute-node CPU experiments. Raw output is the authoritative record."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

POSITIONS = {
    'kiwipete': 'r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1',
    'rook_endgame': '8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1',
    'tactical': 'r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1',
    'ruy_lopez': 'r1bq1rk1/2p1bppp/p1np1n2/1p2p3/4P3/1BP2N1P/PP1P1PP1/RNBQR1K1 b - - 0 9',
    'queens_gambit': 'rn1q1rk1/pbp1bpp1/1p3n1p/3p4/3P3B/2NBPN2/PP3PPP/R2Q1RK1 b - - 3 10',
    'minor_endgame': '8/5pk1/3b2p1/3Pp3/4P3/2N3P1/5PK1/8 w - - 0 1',
}
phase = os.environ.get('CHESS_PHASE', 'pilot')
position = os.environ.get('CHESS_POSITION', 'kiwipete')
ranks = len(Path(os.environ['PBS_NODEFILE']).read_text().splitlines())
fen = POSITIONS[position]
records = Path('results') / os.environ['PBS_JOBID']
records.mkdir(parents=True, exist_ok=True)

def run(backend, depth, threads, split, trial, limit=180):
    limit = int(os.environ.get('CHESS_TIMEOUT', str(limit)))
    command = ['mpirun', '--bind-to', 'none', '-x', 'LD_LIBRARY_PATH', '-x', 'PATH',
               '-np', str(ranks), os.environ.get('CHESS_BINARY', './build/chess_search_mpi'), '--backend', backend,
               '--depth', str(depth), '--threads', str(threads), '--split-depth', str(split),
               '--fen', fen]
    name = f'{backend}-d{depth}-t{threads}-s{split}-r{trial}'
    print('RUN', name, flush=True)
    start = time.monotonic()
    with (records / (name + '.log')).open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            code = 124
    output = (records / (name + '.log')).read_text()
    lines = [line for line in output.splitlines() if line.startswith('backend=')]
    row = dict(re.findall(r'(\w+)=([^\s]+)', lines[0])) if lines else {}
    row.update(position=position, fen=fen, job=os.environ['PBS_JOBID'], phase=phase,
               trial=trial, exit_code=code, launch_seconds=time.monotonic()-start, command=command)
    with (records / 'runs.jsonl').open('a') as out:
        out.write(json.dumps(row) + '\n')
    print(json.dumps({k:v for k,v in row.items() if k not in ('command','fen')}), flush=True)
    return row

if phase == 'pilot':
    for depth in range(4, 10):
        result = run('serial', depth, 1, 1, 0, limit=45)
        if result['exit_code'] or float(result.get('seconds', 0)) >= 1.0:
            break
else:
    if 'CHESS_DEPTH' in os.environ:
        depth = int(os.environ['CHESS_DEPTH'])
    else:
        pilot_path = Path('results') / os.environ['CHESS_PILOT'] / 'runs.jsonl'
        pilot_rows = [json.loads(line) for line in pilot_path.read_text().splitlines()]
        successful = [r for r in pilot_rows if r['exit_code'] == 0 and r.get('seconds')]
        if not successful:
            raise RuntimeError('No successful pilot: do not submit timing data')
        depth = int(successful[-1]['depth'])
        print('SELECTED_PILOT', str(pilot_path), 'depth', depth, flush=True)
    threads = int(os.environ.get('CHESS_THREADS', '4'))
    cases = [('mpi', threads, s) for s in (1, 2, 3)] + [('mpi-pv', threads, 1)]
    if phase == 'scaling':
        cases = [('mpi', threads, 3)]
    elif phase == 'baseline':
        cases = [('mpi', 1, 3)]
    elif ranks == 1:
        cases = [('serial', 1, 1)] + [('mpi', 1, s) for s in (1, 2, 3)] + cases
    for backend, count, split in cases:
        for trial in range(1, 4):
            result = run(backend, depth, count, split, trial,
                         limit=800 if count == 1 and ranks == 1 else 180)
            if result['exit_code']:
                break
