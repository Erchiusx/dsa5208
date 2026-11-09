# Vanda CPU experiments on six additional chess positions

Completed 6 November 2026: **24/24 strong-scaling configurations**, each with
three successful measured trials. Across baselines, four-thread-per-node
comparisons and full-node scaling, **120 groups** have three trials and
scores matching the corresponding serial reference. One earlier timed-out
formal run is retained as an unsuccessful attempt. GPU experiments are
reported separately in the parent experiments directory.

## Where to start

- [RESULTS.md](RESULTS.md): all 120 groups, with medians and validation status.
- [strong_scaling.csv](strong_scaling.csv): 24 full-node points, both serial
  alpha-beta and identical-task one-worker baselines, speedups and efficiency.
- [summary.csv](summary.csv): per-configuration medians and observed ranges.
- [runs.csv](runs.csv): all 384 captured run records, including pilots and timeout.
- [raw/](raw/): unchanged per-run output, session logs, JSONL records, and archived
  runner/PBS scripts when captured by the corresponding job.
- [submitted.tsv](submitted.tsv): submission history, including replaced jobs.

Regenerate the tables from the raw JSONL records, from the repository root:

```sh
python3 project3/scripts/summarize_multiposition.py
```

The summarizer requires three distinct successful trials and agreement with the
serial score before assigning PASS and a formal median. PASS establishes score
agreement under the shared chess rules and evaluator; it does not establish
competitive chess strength or independently validate the move generator.

## Fixed inputs and workload size

Full FEN strings are embedded in [multiposition.py](../../scripts/multiposition.py)
and repeated in every captured run record. Each position keeps the same FEN,
search depth and evaluation across its configurations.

| Position | Depth (plies) | Serial score | Serial median (s) |
|---|---:|---:|---:|
| Kiwipete | 6 | -90 | 5.142270 |
| Rook/pawn endgame | 9 | 100 | 3.187780 |
| Tactical position | 6 | -660 | 1.295080 |
| Ruy Lopez middlegame | 4 | -100 | 0.006350 |
| Queen's Gambit middlegame | 4 | -100 | 0.022143 |
| Bishop/knight/pawn endgame | 9 | 190 | 10.556900 |

The Ruy Lopez and Queen's Gambit FENs were generated from checked legal opening
sequences. The bishop/knight/pawn endgame is a specified synthetic position.
These are fixed algorithm benchmarks, not a sampled dataset of real games.

**The two depth-four middlegames are small-workload cases.** Their successful
pilot search was followed by a failed deeper attempt, so subsequent jobs used
the last successful depth. Their parallel runtimes are below 0.1 seconds and
are dominated by overhead and timing variability. Report them as small-workload
limits, not evidence of useful high-core-count throughput. No timings were
silently removed to improve the curves.

## Compatibility with the earlier Vanda study

- GCC 14.2.0, Open MPI 5.0.7, C++17, `-O2`, OpenMP; same vendored legal-move
  library, material evaluation, legal-move order and terminal rules.
- `mpirun --bind-to none`; one MPI rank per allocated node, PBS `place=scatter`.
- Strategy comparison: 1/2/4 nodes, 4 OpenMP threads per rank, ordinary MPI
  split depths 1/2/3 and seeded-root `mpi-pv` at split depth 1.
- Strong scaling: 1/2/4/10 nodes, 72 threads per rank, split depth 3,
  corresponding to 72/144/288/720 allocated CPU cores.
- Each position has three-repeat serial alpha-beta and one-worker task
  baselines. Fixed depth and split depth are preserved within each curve.
- The executable's `seconds` keeps the earlier search-region definition;
  it excludes launcher startup. `launch_seconds` separately records walltime
  around the launcher. Three fresh process launches per configuration are
  measured; no warmup is discarded, matching the earlier protocol.

Report `T_serial/T_parallel` separately from `T_task(1)/T_task(p)` and
`T_task(1)/(p*T_task(p))`. Different positions and depths are different workloads;
compare their scaling behavior without pooling their raw runtimes into one
curve. Node allocations differ across jobs; session logs preserve hostnames,
CPU information, modules and source hashes. Reported thread counts are configured
counts, not an independent measurement of worker occupancy.

## Exact source and reproduction

Measurements used revision `237f06f`, with `src/main.cpp` SHA-256:

```text
896b1db9e9af57561914f61a4e1da8644e42304e0ad751f26f66150762153707
```

The earlier main scaling source corresponds to `efef92e`, SHA-256
`150790118eb51c0216cf2f812eb780dea16fab85fbc4fa097d38893bda317819`.
The deeper-frontier and serial search implementations are unchanged between
those sources; the later version adds seeded-root search and rank instrumentation.
Do not claim byte-identical source or binaries. Subsequent repository updates
include newer GPU implementations; use the measured revision for exact reproduction.

The PBS runner is [vanda_multiposition.pbs](../../scripts/vanda_multiposition.pbs).
Run it from `project3/` on Vanda after preparing the measured source and scripts.
For example, repeat the final 288-core configuration:

```sh
qsub -l select=4:ncpus=72:mpiprocs=1:ompthreads=72:mem=8gb \
  -l place=scatter -l walltime=00:10:00 \
  -v CHESS_PHASE=scaling,CHESS_POSITION=queens_gambit,CHESS_DEPTH=4,CHESS_THREADS=72 \
  scripts/vanda_multiposition.pbs
```

Results are created under `results/$PBS_JOBID/`. `CHESS_PHASE=full` runs strategy
comparisons and, for one rank, serial and one-worker baselines. `pilot` selects a
bounded depth; `baseline` repeats the one-worker split-depth-three configuration.
Use explicit `CHESS_DEPTH` to reproduce a measured workload rather than reselecting
it. Scripts use Python's standard library and do not submit additional jobs.

## Failed attempts and provenance

The first bishop/knight/pawn pilot (1518525) timed out; dependent full jobs
1518544–1518546 produced no timings. Retry pilot 1518559 and jobs
1518560–1518567 supersede those attempts. Kiwipete's first split-depth-three
one-worker run exceeded 180 seconds; baseline job 1518526 successfully repeated
it with an 800-second per-trial allowance. Formal retries used the same depth.
The final Queen's Gambit 288-core job is 1525334; the 720-core job is 1523620.
Earlier submissions without output are recorded in submitted.tsv and contribute
no successful measurements. The final 288-core job's PBS exit status was 0.

The raw archive includes historical versions of the runner and its timeout
policy. The current runner defaults to 180 seconds for parallel configurations
and 800 seconds for one-worker formal runs. A timeout is not a valid timing.

The project team designed and ran these experiments on Vanda. The report
credits OpenAI Codex for assistance with figures and report drafting and editing.
