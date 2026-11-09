# Report revision audit — 9 November 2026

## Evidence verification

Recomputed all 120 formal configuration medians directly from the 360 successful
raw formal CPU records, independently of the report's plotted data. Trial IDs,
configuration/job identity and scores agree with summary.csv. The archive also
contains pilots and one unsuccessful formal timeout; neither contributes to
successful medians. Ordinary MPI logical node counts are invariant across the
recorded rank/thread layouts for each position and split depth.

## Substantive corrections

1. Replaced six separately scaled mini-plots with two explicitly grouped panels.
   Axes are common within each group and serial parity is visible. Long and short
   workload groups have separately disclosed ranges.
2. Speedup whiskers now include observed variation in both serial and parallel
   times: [min(serial)/max(parallel), max(serial)/min(parallel)]. These are
   unpaired extreme-ratio envelopes, not confidence intervals.
3. Added a direct two-reference plot at 720 cores. Corrected the wording: a
   changed baseline changes the reference-time numerator, not the parallel-time
   denominator in T_reference/T_parallel.
4. Separated work inflation, strategy comparison and GPU phase accounting into
   individual figures. The strategy colors have a true center at parity 1;
   their displayed range includes every cell, including the 8.83 ratio.
5. Added launcher-inclusive timing beside internal search timing. Minor-piece
   speedup is 21.84 under search timing but 5.29 under the wrapper timing;
   tactical is 11.84 versus 1.48. The wrapper serial also includes MPI startup,
   so these are not clean standalone application-response measurements.
6. Clarified that failed depth-five middlegame pilots reached an outer timeout,
   with no search result. Launcher messages alone cannot identify search time
   or establish that the deeper chess workload was infeasible.
7. Documented no explicit pre-search barrier in the frontier path. Maximum
   rank-local duration is not the same as a synchronized global stopwatch.
8. Removed causal attribution of CPU overhead to construction or communication:
   these CPU phases were not separately measured. Work-size groups also differ
   in position and depth, so the experiment identifies no causal size threshold.
9. Distinguished same-allocation strategy comparisons from separately allocated
   serial baselines. Method order is fixed; repeats are not independent node
   allocations and do not establish significance or an optimal strategy.
10. Restricted GPU conclusions to the measured explicit-copy profile. Eliminating
    2.86% of copy time yields 1.029x only if all other measured phases stay fixed;
    this does not bound a redesigned algorithm. Target time includes launch and
    synchronization and cannot establish divergence or occupancy as the cause.
11. Distinguished logical node counts, physical replicated frontier work,
    allocated core-time and energy. Kept the two-baseline identity as arithmetic
    accounting, rather than a causal performance model.
12. Preserved the limits of score agreement under a shared chess library: it is
    not independent rule validation or proof of the deep selected move's value.

## What was not inferred

No statistical confidence interval, weak-scaling result, energy measurement,
optimal rank/thread layout, or general performance claim for all positions
arising from a named chess opening is claimed. No new performance experiment was
run while revising the report. Additional evidence would require matched depth
sweeps, randomized/repeated allocations, per-phase CPU timing and independent
move-value validation.

## Build and visual review

The revised document contains 14 pages, five vector figures and six tables.
The plot script generates figures from archived CPU records and parses the
actual depth-eight GPU profile for phase accounting. The final PDF is rendered
with Poppler for visual inspection; LaTeX reports no overfull boxes or unresolved
references/citations. Earlier GPU measurements and the initial-position study
retain their original sample-size limitations.
