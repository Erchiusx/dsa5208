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

## Multi-station candidate family

The main candidate family uses `spatial_features_<year>`, rather than the
single-station table used for the original baselines. All four models receive
the same target-station history, calendar, identity/location, and lagged
nearest-neighbour aggregates: Logistic Regression, Random Forest, Gradient
Boosted Trees, and a Spark `MultilayerPerceptronClassifier`.

For RF and GBT, seeded negative sampling at a 3:1 target ratio and inverse
frequency weights are retained. Spark's MLP classifier has no `weightCol`, so
its small first run uses a seeded 1:1 negative/positive training sample instead.
Validation and test data retain their natural prevalence in all cases. MLP
numeric inputs are standardized after station one-hot encoding; its initial
architecture is `[input_dimension, 32, 16, 2]`.

The 2024 test set remains unread while comparing these four candidates and
choosing a probability threshold on 2023. Since sampling changes class priors,
raw scores must not be described as calibrated probabilities without a later
calibration step.
