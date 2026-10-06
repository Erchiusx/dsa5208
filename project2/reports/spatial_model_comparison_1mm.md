# Multi-station model selection, 1 mm threshold

All candidates use the leakage-safe `spatial_features_*` table, train on
2017--2022, and are compared on the untouched 2023 validation set. The 2024
test set was evaluated exactly once, only after selecting GBT and freezing its
2023 F1 threshold.

| Candidate | Validation ROC-AUC | Validation PR-AUC | Validation F1 after threshold selection | Decision |
| --- | ---: | ---: | ---: | --- |
| Spatial Logistic Regression | 0.9275 | 0.5246 | 0.5307 | below RF/GBT |
| Spatial Random Forest | 0.9331 | 0.5216 | 0.5717 | below GBT |
| Spatial GBT | 0.9422 | 0.6152 | 0.6010 | selected |
| Spatial MLP `[110, 32, 16, 2]` | 0.4624 | 0.0235 | not selected | failed validation ranking |
| Fixed persistence rule | n/a | n/a | 0.5238 | validation baseline |

GBT's selected probability cutoff is `0.931`. On the final 2024 test set it
obtained precision `0.6156`, recall `0.5737`, F1 `0.5939`, ROC-AUC `0.9349`, and
PR-AUC `0.6052`. The same fixed persistence rule has 2024 F1 `0.5159`.

The uncalibrated GBT scores have Brier score `0.0763` and Brier skill score
`-2.0479` on 2024. This is expected from the 3:1 negative sampling plus inverse
frequency weighting used for classification. The scores must not yet be claimed
as calibrated probabilities; calibration must be fitted on 2023 only before any
new final test evaluation.
