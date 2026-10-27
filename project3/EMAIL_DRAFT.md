Subject: Project 3 proposal: MPI + OpenMP parallel chess search

Dear Professor,

I am considering a fixed-depth chess search for Project 3 and would appreciate
your advice on whether its scope is appropriate.

The serial baseline would be a C++ negamax search with alpha-beta pruning. For
the parallel version, I plan to distribute searches of candidate root moves
across MPI ranks and use OpenMP threads within each rank. I would compare
different rank/thread layouts and root-task assignment strategies, measuring
runtime, speedup, efficiency, nodes searched, and load imbalance on Atlas or
Vanda. The dependency between pruning decisions and the irregular sizes of
subtrees should give meaningful parallelization challenges. I would validate
parallel scores against the serial implementation on fixed positions and
depths.

Would this be a suitable algorithm and parallelization scope for the
assignment? Also, would it be acceptable to use a credited C++ component for
legal move generation and FEN parsing, while implementing the search,
parallel scheduling, experiments, and analysis myself? If you think the scope
should be adjusted, I would welcome your suggestions.

For the performance study, I am considering four fixed chess positions,
several rank/thread configurations up to about 16 CPU workers, and three
repetitions per configuration. OpenMP comparisons could run on one compute
node; I would also test MPI and hybrid configurations across two nodes if
appropriate. Is this a suitable experimental scale for the report, or would
you recommend a different range of core counts, node counts, or test
positions?

Thank you,
[Name]
[Student ID]
