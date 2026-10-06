# Baseline modelling contract

The first baseline is a threshold-specific Logistic Regression model. The caller
supplies `threshold_mm`; the label is `future_30m_rainfall_mm > threshold_mm`.
The saved model is named by that threshold, so inference cannot silently apply a
model trained for a different event definition.

Features are station identity, fixed station location, four past-rainfall totals,
and cyclic hour/month features. The future target, future observation count, and
completeness flags are excluded from the feature vector. Only rows satisfying
`history_60m_complete AND future_30m_complete` are eligible.

The temporal evaluation split is fixed: 2017–2022 train, 2023 validation, and
2024 final test. Training applies inverse-frequency class weights calculated from
training data only. Report ROC-AUC, PR-AUC, precision, recall, and F1; do not
select a model based on the 2024 test metrics.

Compare the learned model with three fixed rule baselines on the same complete
windows: always-negative, rainfall observed in the current five-minute slot, and
past-30-minute rainfall exceeding the same threshold. These rules are not tuned
on the test set.

RF and GBT candidates use the same train/validation split and feature contract.
To fit local resources, all positives and a seeded sample of training negatives
are used; validation and final test sets are never sampled. Choose the candidate
and its probability operating point on 2023 before evaluating its 2024 test
performance.
