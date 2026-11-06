# CPU multi-position results

Archive updated 6 November 2026. All 24 planned strong-scaling configurations completed three successful trials. No GPU results.

PASS requires three distinct measured trials agreeing with the corresponding serial score.
INCOMPLETE groups have no formal median. Failed/time-limited runs remain in runs.csv.

| Position | Depth | Backend | Ranks × threads | Split | Trials | Median (s) | Status |
|---|---:|---|---|---:|---:|---:|---|
| kiwipete | 6 | mpi | 1 × 1 | 1 | 3 | 13.218900 | PASS |
| kiwipete | 6 | mpi | 1 × 1 | 2 | 3 | 41.072700 | PASS |
| kiwipete | 6 | mpi | 1 × 1 | 3 | 3 | 189.148000 | PASS |
| kiwipete | 6 | mpi | 1 × 4 | 1 | 3 | 6.763780 | PASS |
| kiwipete | 6 | mpi | 1 × 4 | 2 | 3 | 15.276700 | PASS |
| kiwipete | 6 | mpi | 1 × 4 | 3 | 3 | 69.214200 | PASS |
| kiwipete | 6 | mpi | 1 × 72 | 3 | 3 | 7.152570 | PASS |
| kiwipete | 6 | mpi | 10 × 72 | 3 | 3 | 0.498987 | PASS |
| kiwipete | 6 | mpi | 2 × 4 | 1 | 3 | 5.793840 | PASS |
| kiwipete | 6 | mpi | 2 × 4 | 2 | 3 | 8.133940 | PASS |
| kiwipete | 6 | mpi | 2 × 4 | 3 | 3 | 35.983700 | PASS |
| kiwipete | 6 | mpi | 2 × 72 | 3 | 3 | 2.350580 | PASS |
| kiwipete | 6 | mpi | 4 × 4 | 1 | 3 | 5.513380 | PASS |
| kiwipete | 6 | mpi | 4 × 4 | 2 | 3 | 3.282020 | PASS |
| kiwipete | 6 | mpi | 4 × 4 | 3 | 3 | 13.007700 | PASS |
| kiwipete | 6 | mpi | 4 × 72 | 3 | 3 | 0.978389 | PASS |
| kiwipete | 6 | mpi-pv | 1 × 4 | 1 | 3 | 5.012500 | PASS |
| kiwipete | 6 | mpi-pv | 2 × 4 | 1 | 3 | 4.869210 | PASS |
| kiwipete | 6 | mpi-pv | 4 × 4 | 1 | 3 | 4.715130 | PASS |
| kiwipete | 6 | serial | 1 × 1 | 1 | 3 | 5.142270 | PASS |
| minor_endgame | 9 | mpi | 1 × 1 | 1 | 3 | 17.102000 | PASS |
| minor_endgame | 9 | mpi | 1 × 1 | 2 | 3 | 44.294200 | PASS |
| minor_endgame | 9 | mpi | 1 × 1 | 3 | 3 | 70.961500 | PASS |
| minor_endgame | 9 | mpi | 1 × 4 | 1 | 3 | 12.038700 | PASS |
| minor_endgame | 9 | mpi | 1 × 4 | 2 | 3 | 25.461600 | PASS |
| minor_endgame | 9 | mpi | 1 × 4 | 3 | 3 | 34.827300 | PASS |
| minor_endgame | 9 | mpi | 1 × 72 | 3 | 3 | 3.789450 | PASS |
| minor_endgame | 9 | mpi | 10 × 72 | 3 | 3 | 0.483354 | PASS |
| minor_endgame | 9 | mpi | 2 × 4 | 1 | 3 | 11.642400 | PASS |
| minor_endgame | 9 | mpi | 2 × 4 | 2 | 3 | 9.982210 | PASS |
| minor_endgame | 9 | mpi | 2 × 4 | 3 | 3 | 13.339400 | PASS |
| minor_endgame | 9 | mpi | 2 × 72 | 3 | 3 | 1.283680 | PASS |
| minor_endgame | 9 | mpi | 4 × 4 | 1 | 3 | 9.905890 | PASS |
| minor_endgame | 9 | mpi | 4 × 4 | 2 | 3 | 3.402240 | PASS |
| minor_endgame | 9 | mpi | 4 × 4 | 3 | 3 | 4.555780 | PASS |
| minor_endgame | 9 | mpi | 4 × 72 | 3 | 3 | 0.647301 | PASS |
| minor_endgame | 9 | mpi-pv | 1 × 4 | 1 | 3 | 11.886000 | PASS |
| minor_endgame | 9 | mpi-pv | 2 × 4 | 1 | 3 | 11.599600 | PASS |
| minor_endgame | 9 | mpi-pv | 4 × 4 | 1 | 3 | 10.852300 | PASS |
| minor_endgame | 9 | serial | 1 × 1 | 1 | 3 | 10.556900 | PASS |
| queens_gambit | 4 | mpi | 1 × 1 | 1 | 3 | 0.116715 | PASS |
| queens_gambit | 4 | mpi | 1 × 1 | 2 | 3 | 0.237602 | PASS |
| queens_gambit | 4 | mpi | 1 × 1 | 3 | 3 | 0.661339 | PASS |
| queens_gambit | 4 | mpi | 1 × 4 | 1 | 3 | 0.037887 | PASS |
| queens_gambit | 4 | mpi | 1 × 4 | 2 | 3 | 0.097852 | PASS |
| queens_gambit | 4 | mpi | 1 × 4 | 3 | 3 | 0.292045 | PASS |
| queens_gambit | 4 | mpi | 1 × 72 | 3 | 3 | 0.087720 | PASS |
| queens_gambit | 4 | mpi | 10 × 72 | 3 | 3 | 0.079817 | PASS |
| queens_gambit | 4 | mpi | 2 × 4 | 1 | 3 | 0.035127 | PASS |
| queens_gambit | 4 | mpi | 2 × 4 | 2 | 3 | 0.053398 | PASS |
| queens_gambit | 4 | mpi | 2 × 4 | 3 | 3 | 0.150471 | PASS |
| queens_gambit | 4 | mpi | 2 × 72 | 3 | 3 | 0.076593 | PASS |
| queens_gambit | 4 | mpi | 4 × 4 | 1 | 3 | 0.026890 | PASS |
| queens_gambit | 4 | mpi | 4 × 4 | 2 | 3 | 0.035042 | PASS |
| queens_gambit | 4 | mpi | 4 × 4 | 3 | 3 | 0.096668 | PASS |
| queens_gambit | 4 | mpi | 4 × 72 | 3 | 3 | 0.071909 | PASS |
| queens_gambit | 4 | mpi-pv | 1 × 4 | 1 | 3 | 0.012648 | PASS |
| queens_gambit | 4 | mpi-pv | 2 × 4 | 1 | 3 | 0.015580 | PASS |
| queens_gambit | 4 | mpi-pv | 4 × 4 | 1 | 3 | 0.025567 | PASS |
| queens_gambit | 4 | serial | 1 × 1 | 1 | 3 | 0.022143 | PASS |
| rook_endgame | 9 | mpi | 1 × 1 | 1 | 3 | 7.948990 | PASS |
| rook_endgame | 9 | mpi | 1 × 1 | 2 | 3 | 28.768500 | PASS |
| rook_endgame | 9 | mpi | 1 × 1 | 3 | 3 | 59.926200 | PASS |
| rook_endgame | 9 | mpi | 1 × 4 | 1 | 3 | 3.194920 | PASS |
| rook_endgame | 9 | mpi | 1 × 4 | 2 | 3 | 13.928000 | PASS |
| rook_endgame | 9 | mpi | 1 × 4 | 3 | 3 | 29.391200 | PASS |
| rook_endgame | 9 | mpi | 1 × 72 | 3 | 3 | 3.431640 | PASS |
| rook_endgame | 9 | mpi | 10 × 72 | 3 | 3 | 0.572371 | PASS |
| rook_endgame | 9 | mpi | 2 × 4 | 1 | 3 | 2.182710 | PASS |
| rook_endgame | 9 | mpi | 2 × 4 | 2 | 3 | 4.971590 | PASS |
| rook_endgame | 9 | mpi | 2 × 4 | 3 | 3 | 11.130400 | PASS |
| rook_endgame | 9 | mpi | 2 × 72 | 3 | 3 | 1.195750 | PASS |
| rook_endgame | 9 | mpi | 4 × 4 | 1 | 3 | 1.127680 | PASS |
| rook_endgame | 9 | mpi | 4 × 4 | 2 | 3 | 3.366960 | PASS |
| rook_endgame | 9 | mpi | 4 × 4 | 3 | 3 | 4.498940 | PASS |
| rook_endgame | 9 | mpi | 4 × 72 | 3 | 3 | 0.830557 | PASS |
| rook_endgame | 9 | mpi-pv | 1 × 4 | 1 | 3 | 1.447820 | PASS |
| rook_endgame | 9 | mpi-pv | 2 × 4 | 1 | 3 | 1.053650 | PASS |
| rook_endgame | 9 | mpi-pv | 4 × 4 | 1 | 3 | 1.028640 | PASS |
| rook_endgame | 9 | serial | 1 × 1 | 1 | 3 | 3.187780 | PASS |
| ruy_lopez | 4 | mpi | 1 × 1 | 1 | 3 | 0.016699 | PASS |
| ruy_lopez | 4 | mpi | 1 × 1 | 2 | 3 | 0.062729 | PASS |
| ruy_lopez | 4 | mpi | 1 × 1 | 3 | 3 | 0.214034 | PASS |
| ruy_lopez | 4 | mpi | 1 × 4 | 1 | 3 | 0.005890 | PASS |
| ruy_lopez | 4 | mpi | 1 × 4 | 2 | 3 | 0.028868 | PASS |
| ruy_lopez | 4 | mpi | 1 × 4 | 3 | 3 | 0.109130 | PASS |
| ruy_lopez | 4 | mpi | 1 × 72 | 3 | 3 | 0.026775 | PASS |
| ruy_lopez | 4 | mpi | 10 × 72 | 3 | 3 | 0.067317 | PASS |
| ruy_lopez | 4 | mpi | 2 × 4 | 1 | 3 | 0.015116 | PASS |
| ruy_lopez | 4 | mpi | 2 × 4 | 2 | 3 | 0.024703 | PASS |
| ruy_lopez | 4 | mpi | 2 × 4 | 3 | 3 | 0.069355 | PASS |
| ruy_lopez | 4 | mpi | 2 × 72 | 3 | 3 | 0.045824 | PASS |
| ruy_lopez | 4 | mpi | 4 × 4 | 1 | 3 | 0.017985 | PASS |
| ruy_lopez | 4 | mpi | 4 × 4 | 2 | 3 | 0.024544 | PASS |
| ruy_lopez | 4 | mpi | 4 × 4 | 3 | 3 | 0.056050 | PASS |
| ruy_lopez | 4 | mpi | 4 × 72 | 3 | 3 | 0.057549 | PASS |
| ruy_lopez | 4 | mpi-pv | 1 × 4 | 1 | 3 | 0.002767 | PASS |
| ruy_lopez | 4 | mpi-pv | 2 × 4 | 1 | 3 | 0.013464 | PASS |
| ruy_lopez | 4 | mpi-pv | 4 × 4 | 1 | 3 | 0.020627 | PASS |
| ruy_lopez | 4 | serial | 1 × 1 | 1 | 3 | 0.006350 | PASS |
| tactical | 6 | mpi | 1 × 1 | 1 | 3 | 3.924320 | PASS |
| tactical | 6 | mpi | 1 × 1 | 2 | 3 | 6.355180 | PASS |
| tactical | 6 | mpi | 1 × 1 | 3 | 3 | 23.135800 | PASS |
| tactical | 6 | mpi | 1 × 4 | 1 | 3 | 1.341040 | PASS |
| tactical | 6 | mpi | 1 × 4 | 2 | 3 | 2.244420 | PASS |
| tactical | 6 | mpi | 1 × 4 | 3 | 3 | 8.389670 | PASS |
| tactical | 6 | mpi | 1 × 72 | 3 | 3 | 0.904860 | PASS |
| tactical | 6 | mpi | 10 × 72 | 3 | 3 | 0.109385 | PASS |
| tactical | 6 | mpi | 2 × 4 | 1 | 3 | 1.142760 | PASS |
| tactical | 6 | mpi | 2 × 4 | 2 | 3 | 1.166690 | PASS |
| tactical | 6 | mpi | 2 × 4 | 3 | 3 | 4.799380 | PASS |
| tactical | 6 | mpi | 2 × 72 | 3 | 3 | 0.374902 | PASS |
| tactical | 6 | mpi | 4 × 4 | 1 | 3 | 1.123920 | PASS |
| tactical | 6 | mpi | 4 × 4 | 2 | 3 | 0.556679 | PASS |
| tactical | 6 | mpi | 4 × 4 | 3 | 3 | 2.274710 | PASS |
| tactical | 6 | mpi | 4 × 72 | 3 | 3 | 0.171695 | PASS |
| tactical | 6 | mpi-pv | 1 × 4 | 1 | 3 | 0.778716 | PASS |
| tactical | 6 | mpi-pv | 2 × 4 | 1 | 3 | 0.804408 | PASS |
| tactical | 6 | mpi-pv | 4 × 4 | 1 | 3 | 1.225990 | PASS |
| tactical | 6 | serial | 1 × 1 | 1 | 3 | 1.295080 | PASS |

Failed/time-limited recorded runs: 1.

Timing is the executable search region; runs.csv separately retains launcher walltime.
Hardware/software provenance is preserved in the adjacent session.log files.
