# Vanda CPU pilot results

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
raw log. This is a **feasibility run**, not a scaling point: it changes the
split depth and search work relative to the single-node pilot, has no
repetitions, and excludes process startup from the program's timed region.

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
nodes. Each row below has three trials in one PBS allocation. The 720-core
pilot above has one trial; a three-trial job was submitted separately.

| PBS job | Nodes | Allocated cores | Internal search times (s) | Median (s) |
| --- | ---: | ---: | --- | ---: |
| 1499947 | 1 | 72 | 9.28207, 8.95906, 9.09414 | 9.09414 |
| 1499950 | 2 | 144 | 3.28496, 3.04777, 3.03716 | 3.04777 |
| 1499952 | 4 | 288 | 1.9669, 1.94508, 1.74921 | 1.94508 |

All trials agree on 929,868,807 search nodes, score -100, and move `a2a3`.
The 72-to-144-core median ratio is 2.98 and the 72-to-288-core ratio is
4.68. These exceed ideal linear scaling; task distribution, node variation,
and cache effects need more investigation before interpreting the cause.
The numbers measure only the application's search region. PBS walltime also
includes repeated MPI launches and other setup, so it should be reported
separately. `scripts/summarize_vanda.py` regenerates `runs.csv` from the
preserved raw logs.

Next, finish the 720-core repeated run and obtain a one-worker decomposition
baseline. Both the serial alpha-beta reference and the one-worker task
decomposition should remain visible: they answer different scaling questions.
