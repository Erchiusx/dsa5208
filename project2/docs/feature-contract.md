# Feature and target contract

Each feature row represents a prediction made at `prediction_ts` for one
`station_id`. It contains only station identity/location, Singapore-time calendar
features, and rainfall observed at or before that time.

`future_30m_rainfall_mm` is the sum of readings at the six five-minute slots in
`(prediction_ts, prediction_ts + 30 minutes]`. It is deliberately continuous
and threshold-independent. For a model input threshold `r`, the classification
label is constructed later as `future_30m_rainfall_mm > r`.

Rows with incomplete history or target windows are retained for audit but must
be excluded from model training with `history_60m_complete AND
future_30m_complete`. This prevents missing monitoring readings from being
silently interpreted as zero rainfall, and prevents future target data from
entering predictor columns.

## Multi-station extension

`spatial_features_<year>` retains every base feature and adds aggregates from
the eight geographically nearest *other* stations. Source timestamps are first
rounded to a nominal five-minute slot solely to reconcile the source's `:00`
and `:59` timestamp conventions. A target at time `t` uses only neighbour
values from the preceding nominal slot. Thus no neighbour value can be newer
than the target observation, even at the one-second export offset.

Distance-weighted neighbour totals for 5, 15, 30, and 60 minutes, the neighbour
30-minute maximum, the fraction of neighbours currently raining, and explicit
availability/count features are stored. An unavailable neighbour is never
treated as an observed zero: aggregate values are zero-filled only alongside
availability features that identify this condition.
