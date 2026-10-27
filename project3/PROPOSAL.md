# Project 3: Parallel alpha-beta chess search

Status: instructor approved the topic and credited external move-generation
library in their reply. The instructor encouraged OpenMP GPU offload,
experiments beyond two nodes (Vanda permits up to 720 CPU cores), and an
extensive explanation of chess search for readers unfamiliar with engines.
This is a design plan, not a record of completed implementations or runs.

## Question and algorithm

How do task granularity, scheduling, CPU rank/thread layout, and optional GPU
offload affect the correctness, runtime, search work, and scaling of a
fixed-depth alpha-beta chess search?

For each legal root move in a FEN position, negate the opponent's search score
(negamax). Search recursively to a fixed depth. Alpha and beta bound scores
that can still influence the decision; if a bound proves a move cannot improve
the result, skip the remaining branch. At the depth limit, use a deterministic
chess evaluation (initially material, possibly simple piece-square terms).
Handle checkmate, stalemate, and other terminal positions explicitly. Fix the
move order and tie rule. This description, a small worked tree, and a
chess-specific example will introduce the algorithm in the report before any
parallel code or results.

We implement search, task scheduling, instrumentation, benchmarks, and
validation in C++. A credited external library can provide legal moves and
FEN parsing, as the instructor approved. Select one with a compatible licence;
record its version and the functions used. Playing strength, neural
evaluation, and distributed transposition tables are outside the initial
scope. Keep transposition tables disabled for the main controlled comparison.

## CPU implementations and design comparisons

1. **Serial alpha-beta reference.** Ordered negamax with alpha-beta pruning;
   instrument nodes, cutoffs, runtime, and the best score.
2. **Serial task decomposition.** Make independent subtrees with exact
   full-window searches and combine their scores by min/max on the frontier.
   This is a second serial baseline with the same extra work as the basic
   parallel design, allowing scheduling overhead and lost pruning to be
   separated.
3. **Root split, MPI + OpenMP.** Distribute root-move tasks among ranks and
   execute each rank's tasks with OpenMP threads. Compare fixed assignment
   and demand-driven scheduling if time permits. Each task owns its board and
   search state; only the designated host thread makes MPI calls.
4. **Deeper split for many cores.** Root tasks alone provide only as many
   tasks as legal root moves. Create a frontier at depth 2 or 3, preserving the
   min/max relationships of ancestors when merging exact subtree scores.
   Compare task count, load imbalance, extra nodes, and runtime with the root
   split. Cap frontier size and task memory. If independent full-window tasks
   cost too much, explore search-aware splitting: search a promising child
   first and release further siblings using its bound. Bounds returned by
   pruned subtrees require a separately verified merge rule.

The initial CPU deliverable is the correct serial reference plus root split
and one deeper frontier. A better bound-sharing scheduler is an extension,
not a prerequisite for a valid comparison. Record the coordinator's CPU use
and count it in resource allocation. Do not describe a scheduler as dynamic
until an actual task-request or work-stealing mechanism is implemented.

## GPU offload exploration (secondary, bounded)

OpenMP's `target teams distribute parallel for` can execute independent loop
iterations on a GPU. Our working hypothesis is that alpha-beta's data-dependent
cutoffs, uneven subtrees, small per-node evaluation, and host/device transfer
make GPU offload a poor fit for this simple evaluator. The CPU MPI + OpenMP
search remains the main project. Recursive search with irregular branches and
a typical host-side C++ chess library is not automatically device compatible.
Treat the instructor's offload suggestion as a measured feasibility and design
study:

1. On a Vanda GPU node, compile a minimal OpenMP target program and verify
   that it runs on the device rather than silently falling back to the CPU
   (for example, check `omp_is_initial_device()` inside the target region and
   run with `OMP_TARGET_OFFLOAD=MANDATORY`). Record compiler, flags, GPU model,
   and runtime environment.
2. Define a compact, device-safe board representation and a batch of
   independent positions. Offload a simple evaluation kernel and compare
   its exact scores with the CPU evaluation. Measure transfer, kernel, and
   total times over batch sizes; this is a component benchmark, not yet GPU
   search acceleration.
3. If compatible move generation and sufficient task volume are achievable,
   offload whole independent frontier subtrees and compare end-to-end search
   with the CPU task version on identical positions and depth. Otherwise,
   evaluate whether batched leaf evaluation can be integrated without
   excessive speculative work or per-leaf transfer overhead. Report the
   measured limitation plainly if neither integration is worthwhile.

Stop the GPU branch after the verified component benchmark if its transfer
and launch costs swamp evaluation, or if porting legal move generation would
consume the time needed for the CPU scaling and correctness results. State
that outcome as a feasibility finding, not as a GPU search implementation.

OpenMP target regions need explicit work distribution; a lone `target` region
does not spread tasks across GPU threads. The GPU result must use the same
evaluation and return the same search score as the CPU version before any
speedup claim. GPU scaling is separate from CPU scaling: count CPU workers,
GPUs, and allocated nodes separately.

## Correctness

- Compare legal moves on selected positions with the chosen library's
  reference behavior and test terminal and special-rule cases it supports.
- At shallow depths, compare serial alpha-beta with exhaustive minimax under
  the same evaluation and terminal rules.
- At benchmark depths, require every CPU or GPU configuration to match the
  serial best score. Check that its chosen legal move has that score under
  an exact full-window root search. Equal-score best moves may differ.
- Repeat runs to find races. Preserve raw per-position scores, not only an
  aggregate pass/fail count.

## Bounded experiment plan on Vanda

Start with four fixed FEN positions: opening, middlegame, tactical position,
and endgame. Pilot depths so the single-worker search is measurable and both
serial baselines remain affordable. For a given position, keep the depth,
evaluation, move order, compiler build, and hardware class fixed. Use three
repetitions and report median wall time and variability. For MPI jobs, the
elapsed job time is determined by the slowest participating rank.

**Stage A, one node:** measure 1, 2, 4, 8, 16, 32, and possibly 64 CPU workers,
subject to the node's physical cores. Compare rank/thread layouts at equal
worker counts (for example, 1x8, 2x4, 4x2, 8x1). Compare root and deeper
frontiers to show when additional tasks repay their extra search work.

**Stage B, multiple nodes:** use representative positions and a frontier with
enough tasks; test 1, 2, 4, and 8 nodes, then 16 or more nodes only if the
smaller runs show useful scaling and the cluster allocation permits it.
Record ranks per node, threads per rank, physical cores, binding, and total
allocated cores. The 720-core figure is a possible upper limit to explore,
not a target that automatically makes sense for this search. If a deeper
frontier increases search work prohibitively or task count is too small,
report the scaling limit rather than forcing a larger run.

**Stage C, GPU:** run the device smoke test and a bounded batch-size sweep;
perform end-to-end CPU-versus-GPU search runs only after correctness and
device compatibility checks pass.

Report strong-scaling speedup S(p) = T(1)/T(p) and efficiency E(p) = S(p)/p
for comparable CPU configurations. Also show task count, nodes, cutoffs,
per-rank time, and the ratio of task-decomposed work to serial alpha-beta
work. Keep a distinct baseline for GPU comparisons. Do not claim weak scaling
by simply increasing depth, since pruning and branching change work
nonlinearly. Time spent in task generation, communication, host/device
transfer, and search should be separated when measurable.

## Report and submission

The report should first teach minimax, negamax, alpha-beta bounds, and why
move ordering and pruning make the tree irregular. Then present the serial
reference, task-frontier reconstruction, MPI/OpenMP mapping, GPU feasibility,
correctness evidence, runtime figures from Vanda, scaling and efficiency,
limitations, and AI-usage disclosure. Deliver C++ source, exact build and
batch commands, fixed inputs, benchmark scripts, and raw results with a
README. State which algorithms were implemented and which remained proposals.

## Technical background

- Feldmann et al., “Distributed Game-Tree Search” (1989):
  https://journals.sagepub.com/doi/abs/10.3233/ICG-1989-12203
- Kuszmaul et al., “Massively Parallel Chess” (1994):
  https://people.csail.mit.edu/bradley/papers/JoergKu94.pdf
- OpenMP 5.0, target teams distribute parallel loop construct:
  https://openmp.org/spec-html/5.0/openmpsu87.html
- LLVM OpenMP offload support and configuration:
  https://openmp.llvm.org/SupportAndFAQ.html
- OpenMP 5.0, `OMP_TARGET_OFFLOAD` environment variable:
  https://openmp.org/spec-html/5.0/openmpse65.html
