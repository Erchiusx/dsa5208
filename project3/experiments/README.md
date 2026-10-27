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
1-thread counterpart. Open MPI 5 binds a single rank to a core by default,
which may explain this, but the recorded runs did not report affinity. This
hypothesis needs a controlled rerun with binding reported. The two-node speedup
of 1.63 relative to the one-node 4-thread run is **not** speedup over the
serial alpha-beta reference.

The CPU PBS script now records binding and defaults to `--bind-to none` for
hybrid MPI/OpenMP runs. Use `JOB_BINDING=default` to reproduce the previous
launcher policy. Compare default and none with otherwise identical PBS
allocations before expanding the node count. Open MPI's
[5.0.7 mpirun documentation](https://docs.open-mpi.org/en/v5.0.7/man-openmpi/man1/mpirun.1.html)
describes this threading and binding interaction.

After the affinity check, measure one split depth and fixed position at
1, 2, 4, and 8 workers, then larger worker counts only if the task count and
single-node timing justify them. Record at least three independent runs per
configuration and use their median. Include a 1-worker task-decomposition
baseline as well as the serial alpha-beta baseline: they answer different
scaling questions.
