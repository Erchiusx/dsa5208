# Cleaning contract

The raw annual CSV files are immutable inputs. The cleaning pipeline reads them
with an explicit schema and writes a separate, partitioned Parquet dataset.

Records are rejected only when the observation timestamp, station identifier,
rainfall value, coordinates, or unit are invalid. A negative rainfall amount is
invalid; zero rainfall is a valid observation. Duplicate `(station_id,
observation_ts)` records are resolved by retaining the newest `update_ts`, then
the newest `reading_update_ts`.

The pipeline does **not** manufacture five-minute observations: it reports gaps
larger than five minutes per station. Any imputation belongs to an explicitly
justified later feature-engineering stage.

Run the full cleaning job from the repository root:

```bash
python project2/scripts/clean_rainfall.py
```

For an isolated annual run, use `--years 2017`. Outputs under `data/interim/`
are ignored by Git; the JSON quality report makes every cleaning run auditable.
