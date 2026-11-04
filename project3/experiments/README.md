# Vanda CPU and GPU experiments

All rows below use the initial-position FEN, depth 7, GCC 14.2.0,
OpenMPI 5.0.7, and one MPI rank per node. Times are **single runs**, not
report-ready medians. The corresponding complete stdout/stderr captures are
in `raw/`. The MPI launcher used its default binding in these runs.

| PBS job | Nodes | Threads/rank | Backend | Split depth | Search nodes | Search seconds | Score |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 1499874 | 1 | 1 | serial | 1 | 927,081 | 0.192181 | 100 |
| 1499885 | 1 | 1 | mpi | 2 | 28,716,385 | 6.17835 | 100 |
| 1499869 | 1 | 4 | mpi | 2 | 28,716,385 | 7.34836 | 100 |
| 1499875 | 2 | 4 | mpi | 2 | 28,716,385 | 4.51899 | 100 |
| 1499886 | 1 | 4 | mpi | 1 | 16,236,941 | 4.66548 | 100 |

The best move printed in every row was `a2a3`. The serial alpha-beta search
visits about 31 times fewer nodes than the depth-2 task decomposition because
the independent tasks use full windows; the latter cannot share alpha/beta
bounds across the frontier. The 4-thread depth-2 run is slower than its
1-thread counterpart. A controlled rerun below confirms that Open MPI's
default one-core binding caused much of this slowdown. The two-node speedup
of 1.63 relative to the one-node 4-thread run is **not** speedup over the
serial alpha-beta reference.

The CPU PBS script now records binding and defaults to `--bind-to none` for
hybrid MPI/OpenMP runs. Use `JOB_BINDING=default` to reproduce the previous
launcher policy. A controlled rerun on CN-017 confirmed the binding issue:

| PBS job | Binding report | Threads | Search seconds | Search nodes |
| --- | --- | ---: | ---: | ---: |
| 1499905 | `Rank 0 bound to package[1][core:49]` | 4 | 6.22858 | 28,716,385 |
| 1499911 | `Rank 0 is not bound` | 4 | 2.432 | 28,716,385 |

Both jobs exited with status 0 and returned score 100 / move `a2a3`.
Removing the one-core MPI binding reduced measured search time by 2.56x in
this pair. This is one observation, so repeat for final figures. Open MPI's
[5.0.7 mpirun documentation](https://docs.open-mpi.org/en/v5.0.7/man-openmpi/man1/mpirun.1.html)
describes this threading and binding interaction.

## Corrected-binding scaling pilot

These additional single runs used `--bind-to none`, depth 7 and the same
initial-position FEN. Each job returned score 100 / move `a2a3` and exited 0.
The two- and four-node jobs requested `place=scatter`; PBS and the logged
hostnames confirm distinct machines.

| PBS job | Nodes | Threads total | Split depth | Search seconds | Search nodes |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1499914 | 1 | 4 | 1 | 1.20833 | 16,236,941 |
| 1499911 | 1 | 4 | 2 | 2.432 | 28,716,385 |
| 1499915 | 2 | 8 | 2 | 1.49415 | 28,716,385 |
| 1499917 | 4 | 16 | 2 | 0.714599 | 28,716,385 |

For the fixed split-depth-2 work, the four-node run is 3.40x faster than
the one-node run (85.1% efficiency for the 4x resource increase). Relative
to the 1-worker task-decomposition run, it is 8.65x faster at 16 workers
(54.0% efficiency). It remains 3.72x slower than the serial alpha-beta
reference, which prunes substantially more of the game tree. These ratios
are provisional because each configuration has only one measured run.

## Depth-8 workload and 720-core feasibility

The depth-8 serial baseline in job 1499919 ran three trials on CN-016:
5.33762, 5.34012, and 5.34224 seconds (median 5.34012). Every trial
returned score -100 / move `a2a3` and visited 25,604,258 nodes. A
single-node 4-thread depth-2 pilot (1499920) visited 420,118,518 nodes and
took 42.3628 seconds, showing how the decomposition loses pruning. A
depth-7, split-depth-3 pilot (1499922) produced 9,323 frontier nodes and
returned the same depth-7 score as the other backends.

At the user's request, job 1499923 successfully requested 10 scattered
nodes, each with 72 CPUs: 720 allocated CPU cores. It used 10 MPI ranks and
72 requested OpenMP threads per rank, depth 8, split depth 3. PBS reported
exit status 0, 53 seconds of job walltime, and the program reported 1.59317
seconds of internal search time. The search visited 929,868,807 nodes and
returned score -100 / move `a2a3`, matching the depth-8 serial baseline.
One allocated host was a GN-A40 node; the hostname list is preserved in the
raw log. This is a **feasibility run**, not a finalized scaling point: it
changes the split depth and search work relative to the earlier single-node
depth-2 pilot, has no repetitions, and excludes process startup from the
program's timed region. The later split-depth-3 series and one-worker
baseline provide the like-for-like comparison used in the draft figure.

The Open MPI PRTE PBS component emits a `libpbs.so.0` warning and uses SSH
for rank launches, so we checked CPU isolation explicitly. Job 1499940
requested 4 CPUs on CN-017. The PBS shell and the MPI rank with
`--bind-to none` both reported `Cpus_allowed_list: 49,51,53,55` and joined
the job's PBS cgroup. The rank with `--map-by ppr:1:node:PE=4 --bind-to core`
reported the same four CPUs. This confirms the unbound MPI rank remains
inside the PBS CPU allocation on that tested node. The raw probe output is
`raw/1499940-affinity.txt`; the script is `scripts/vanda_affinity.pbs`.

## Depth-8 strong-scaling series (full nodes)

For a like-for-like comparison to 720 cores, split depth 3 and all other
search parameters were held fixed while changing the number of 72-core
nodes. Each row below has three trials in one PBS allocation. The earlier
720-core feasibility run above remains a separate single-trial check.

| PBS job | Nodes | Allocated cores | Internal search times (s) | Median (s) |
| --- | ---: | ---: | --- | ---: |
| 1499947 | 1 | 72 | 9.28207, 8.95906, 9.09414 | 9.09414 |
| 1499950 | 2 | 144 | 3.28496, 3.04777, 3.03716 | 3.04777 |
| 1499952 | 4 | 288 | 1.9669, 1.94508, 1.74921 | 1.94508 |
| 1499963 | 10 | 720 | 1.59305, 1.75406, 1.79214 | 1.75406 |

All trials agree on 929,868,807 search nodes, score -100, and move `a2a3`.
The 72-to-144-core median ratio is 2.98 and the 72-to-288-core ratio is
4.68. These exceed ideal linear scaling; task distribution, node variation,
and cache effects need more investigation before interpreting the cause.
The numbers measure only the application's search region. PBS walltime also
includes repeated MPI launches and other setup, so it should be reported
separately. `scripts/summarize_vanda.py` regenerates `runs.csv` from the
preserved raw logs.

A one-worker decomposition run (1499970) with the **same** depth-8,
split-depth-3 search visited 929,868,807 nodes in 198.129 seconds and
exited 0. Using this single run as the work-preserving baseline gives the
72-core median a speedup of 21.79 (30.3% efficiency), the 144-core median
65.01 (45.1%), and the 288-core median 101.86 (35.4%). The one-time
720-core three-trial median gives 112.95 (15.7%) by this definition. Against
the serial alpha-beta median, the 720-core median is 3.04x faster because it
performs about 36 times as many search-node visits. The one-worker baseline
has only one trial, so the speedup and efficiency estimates inherit that
baseline uncertainty. The 720-core repeated job used ten distinct CN hosts
and the same source hash as the earlier pilot. All three trials matched the
serial score and move; its full output is `raw/1499963.txt`. PBS history for
this job had expired when collected, so the output proves completion of all
three trials but does not independently recover its PBS exit status or
walltime.
The current vector figure is [`figures/scaling.pdf`](../figures/scaling.pdf),
built from `figures/scaling.tex` with `pdflatex` and uses the three-trial
median for 720 cores.

## OpenMP GPU-offload feasibility

The first NVHPC job (1499966) reached an A40 node but failed compilation:
`nvc++` could not find `<functional>`. Explicitly selecting Vanda's GCC
13.2 toolchain with `--gcc-toolchain=$EBROOTGCCCORE` resolved this. Three
subsequent jobs compiled, exited 0, and reported `ran_on_device=1` with
`OMP_TARGET_OFFLOAD=MANDATORY`. Each GPU score and move matched the serial
search for the same initial position and depth.

| PBS job | Depth | CPU-built tree nodes | GPU total (s) | GPU target (s) | Serial search (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1499986 | 3 | 9,322 | 0.246888 | 0.244381 | 0.000125092 |
| 1499992 | 4 | 206,603 | 0.270310 | 0.238880 | 0.000237436 |
| 1518429 | 5 | 5,072,212 | 1.798000 | 0.660136 | 0.007303230 |

The GPU path constructs the entire legal tree on the CPU, copies it to the
device, then searches independent root branches on the GPU. From depths 3
to 4, the target region remained near 0.24 seconds while the CPU-built tree
grew more than 20-fold. At depth 5, the tree reached 5,072,212 nodes and
the target region took 0.660 seconds. The current counters
do not separate launch, transfer, and kernel time. The GPU total is about
1,974x, 1,138x, and 246x slower than serial alpha-beta at
depths 3, 4, and 5 respectively. At depth 5, CPU preparation alone took
1.138 seconds, about 156 times the serial search time. This job required
raising `--max-tree-nodes` from 2 million to 7 million; PBS reported a
19-second total job walltime. The CPU-built tree itself grows quickly,
so this implementation is a bounded feasibility study rather than a
competitive chess-engine GPU design. GPU and serial visit different node
counts because the GPU root branches use independent full windows. The raw
GPU run and compiler logs are saved in `raw/`. The depth-5 log is
`raw/1518429-gpu.txt`; its PBS history records exit status 0.

## On-demand GPU chunks

The `gpu-chunk` backend uses the CPU chess library to generate only reached
subtrees. CPU alpha-beta retains pruning above a bounded chunk; the GPU
searches that chunk's immediate child branches. `tree_nodes` counts all
nodes generated across chunks, not peak resident nodes. `gpu_chunks` counts
chunk target launches (the device probe adds one more target region). These are single-trial exploratory runs, each paired
with a serial search in the same PBS job. All recorded jobs exited 0,
reported `ran_on_device=1`, and matched serial score and move.

| PBS job | Depth | Chunk depth | Generated nodes | GPU launches | GPU total (s) | Serial (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1518504 | 5 | 3 | 615,039 | 58 | 0.440220 | 0.004531 |
| 1518507 | 5 | 2 | 431,665 | 844 | 0.520517 | 0.004526 |
| 1518510 | 6 | 3 | 11,155,745 | 963 | 4.249360 | 0.144860 |
| 1518511 | 7 | 3 | 12,920,761 | 1,042 | 5.570290 | 0.196487 |
| 1518515 | 8 | 3 | 428,791,429 | 30,619 | 154.521000 | 3.940450 |

At depth 5, the original full-tree GPU version generated 5,072,212 nodes.
The chunk-depth-3 version generated 615,039, but required 58 target launches.
Chunk depth 2 generated still fewer nodes at the cost of 844 launches and a
longer target time. These cross-job comparisons remain preliminary because
the full-tree run and chunk runs used different A40 nodes.

Job `1518527` ran the four backends three times each in one A40 allocation.
The medians below come from `raw/1518527-gpu-compare.txt`; every run returned
score 100, move `b2b3`, and GPU runs reported `ran_on_device=1`. PBS exit
status was 0. These are within-job comparisons, but each backend ran in
fixed order, so the three trials do not remove possible order effects.

| Depth-5 backend | Generated nodes | Chunk launches | Median total (s) | Median target (s) |
| --- | ---: | ---: | ---: | ---: |
| Serial CPU | — | — | 0.007177 | — |
| Original GPU full tree | 5,072,212 | 1 | 1.656630 | 0.560216 |
| GPU chunk depth 2 | 431,665 | 844 | 0.501165 | 0.419824 |
| GPU chunk depth 3 | 615,039 | 58 | 0.427455 | 0.310383 |

Thus chunk depth 3 is about 3.88 times faster than the original GPU backend
at depth 5, yet about 60 times slower than the serial CPU search. At depth 8,
the chunked backend generated 428.8 million cumulative tree nodes and spent
96.669 seconds in target regions; its 154.521-second total was about 39 times
the paired serial time. The exact source hashes and allocations are in the logs.

## GPU transfer and search profiling

PBS job `1518578` used the `gpu-profile` and `gpu-chunk-profile` backends on
one A40 (GN-A40-017). It completed with exit status 0. All four profiled
configurations matched the paired serial score and move, and each GPU run
reported `ran_on_device=1`. Raw output is in
`raw/1518578-gpu-profile.txt`. The depth-5 configurations ran three times;
depth 8 ran once. The table uses medians for depth 5.

The profiling backends replace the implicit OpenMP map with explicit device
allocations and `omp_target_memcpy` calls. `H2D` and `D2H` measure those copy
calls. `Target search` measures the synchronous target region, including
launch and synchronization; it is **not pure device computation time**.
`CPU build` includes constructing legal trees with the third-party library.
`Probe` is a separate initial target call to verify real GPU execution.
The timings are a new instrumented run, so compare its own phase totals
instead of subtracting them from the older implicit-map runs.

| Configuration | Total (s) | CPU build (s) | Probe (s) | H2D (s) | Target search (s) | D2H (s) | Uploaded bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Depth 5, full tree | 1.304 | 0.762 | 0.149 | 0.035 | 0.358 | <0.001 | 397,397,422 |
| Depth 5, chunk 2 | 0.458 | 0.051 | 0.150 | 0.014 | 0.218 | 0.022 | 33,779,915 |
| Depth 5, chunk 3 | 0.361 | 0.073 | 0.144 | 0.005 | 0.136 | 0.002 | 48,079,344 |
| Depth 8, chunk 3 | 154.620 | 57.525 | 0.243 | 3.563 | 92.313 | 0.853 | 33,541,484,954 |

At depth 8, explicit copies totaled 4.417 seconds (2.9% of total), CPU
construction took 37.2%, and the combined target launch/search phase took
59.7%. The GPU allocation/free total was 0.0935 seconds; remaining host
bookkeeping was about 0.029 seconds. At depth 5 with chunk depth 3, explicit
copies took about 0.0071 seconds (2.0%) while the one-time device probe took
0.144 seconds (39.9%). The probe cost is specific to a fresh process and
would be amortized across multiple searches in a persistent engine. Because
the target search timer includes launch overhead, these measurements do not
determine how much of its 92.313 seconds was device traversal alone.
The paired depth-5 serial median was 0.004981 seconds. CPU tree construction
alone was about 153 times that for the full-tree GPU method and 15 times
that for chunk depth 3. At depth 8, CPU tree construction took 57.525 seconds
against 3.689 seconds for the complete paired serial search. This is a
work-amplification effect: a reached chunk is generated in full before
device-side pruning can skip any of its branches.
