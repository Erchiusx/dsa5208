# Data contract

`raw/` holds one unmodified CSV for every year from 2017 through 2024. Do not
edit those files in place. Cleaning, temporal alignment, labels, and features
belong in `interim/` and `processed/` so the exact source data remain auditable.

`metadata/source-collection-2279.json` is the official collection response
captured on 2026-09-29. The annual `datasetSize` values are source-declared byte
counts. They do not equal the size of the CSV object exported by the portal.

The dataset owner cautions that missing records may occur and the data have not
undergone official climate-data quality control. Treat missing intervals as a
data-quality finding, rather than silently imputing them.
