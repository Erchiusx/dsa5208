# Seeded-root MPI/OpenMP pilot

This variant first searches the initial legal root move with a full alpha-beta
window. Its score becomes a fixed bound for the remaining root moves, which
are distributed across MPI ranks and OpenMP threads. It exposes only 19
parallel root tasks for the initial position. The code was synced to a
separate Vanda directory, `~/dsa5208/project3-pv/`, so the pending
full-frontier 720-core job in `~/dsa5208/project3/` keeps its original source.

All trials used the initial-position FEN, depth 8, split depth 1, four
threads per rank, Open MPI `--bind-to none`, and source SHA-256
`8ae6851b5106bdddc412d6fc47c5b659957611598db2d55a198c150960ac0b94`.
Each PBS job exited 0. Times exclude MPI process launch. Hostnames and the
full output are in `raw/`.

| PBS job | Nodes | Hosts | Search times (s) | Median (s) |
| --- | ---: | --- | --- | ---: |
| 1500009 | 1 | GN-A40-074 | 3.03251, 3.01045, 2.67925 | 3.01045 |
| 1500079 | 2 | GN-A40-074, GN-A40-076 | 2.85346, 2.82751, 2.86609 | 2.85346 |
| 1500114 | 4 | CN-148, CN-149, CN-152, CN-153 | 4.20480, 4.20550, 4.20217 | 4.20480 |

Every trial returned score -100, move `a2a3`, and 25,604,258 search nodes,
matching the serial alpha-beta baseline's result and work count. The four-node
configuration is slower than the two-node configuration. These allocations
used different hosts, so the cause cannot be isolated from this table alone.
The next instrumented run will record first-move time and each rank's work
to distinguish serial setup from load imbalance.
