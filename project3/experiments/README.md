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

After the affinity check, measure one split depth and fixed position at
1, 2, 4, and 8 workers, then larger worker counts only if the task count and
single-node timing justify them. Record at least three independent runs per
configuration and use their median. Include a 1-worker task-decomposition
baseline as well as the serial alpha-beta baseline: they answer different
scaling questions.
