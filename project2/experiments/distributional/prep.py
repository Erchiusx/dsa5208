#!/usr/bin/env python3
"""Raw CSV -> slot-aligned feature matrices for distributional 30-min rainfall models.

Conventions (aligned with project2's leakage contract):
  * timestamps are rounded to the nominal 5-minute slot (reconciles :59 / :00 exports);
  * duplicates per (station, slot) keep the newest update timestamp;
  * own-station history uses slots t-11..t (exactly 60 min), target is the sum of
    slots t+1..t+6 (30 min); a row is eligible only if both windows are complete;
  * neighbour information is lagged one slot (ends at t-1), as in spatial.py.
Outputs one Parquet file per year under data/processed/dist_features/.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import duckdb
import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
RAW = PROJECT / "data" / "raw"
OUT = PROJECT / "data" / "processed" / "dist_features"
DB = PROJECT / "data" / "interim" / "dist.duckdb"
K = 8


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def load_slots(con, years):
    con.execute("DROP TABLE IF EXISTS obs")
    files = [str(RAW / f"rainfall_{y}.csv") for y in years]
    con.execute(f"""
    CREATE TABLE obs AS
    WITH raw AS (
      SELECT * FROM read_csv({files!r}, header=true, all_varchar=true)
    ), parsed AS (
      SELECT trim(station_id) AS station,
             try_cast(timestamp AS TIMESTAMPTZ) AS ts,
             try_cast(update_timestamp AS TIMESTAMPTZ) AS uts,
             try_cast(reading_update_timestamp AS TIMESTAMPTZ) AS ruts,
             try_cast(location_longitude AS DOUBLE) AS lon,
             try_cast(location_latitude AS DOUBLE) AS lat,
             try_cast(reading_value AS DOUBLE) AS y,
             trim(reading_unit) AS unit
      FROM raw
    ), valid AS (
      SELECT station, CAST(round(epoch(ts) / 300) * 300 AS BIGINT) AS slot, uts, ruts, lon, lat, y
      FROM parsed
      WHERE ts IS NOT NULL AND station IS NOT NULL AND length(station) > 0
        AND y IS NOT NULL AND y >= 0 AND unit = 'mm'
        AND lon BETWEEN 103 AND 105 AND lat BETWEEN 1 AND 2
    )
    SELECT station, slot, lon, lat, y FROM (
      SELECT *, row_number() OVER (PARTITION BY station, slot
                                   ORDER BY uts DESC NULLS LAST, ruts DESC NULLS LAST) AS rk
      FROM valid)
    WHERE rk = 1
    """)
    n = con.execute("SELECT count(*), count(DISTINCT station) FROM obs").fetchone()
    print(f"obs rows={n[0]:,} stations={n[1]}", flush=True)


def station_features(con):
    con.execute("DROP TABLE IF EXISTS sf")
    con.execute("""
    CREATE TABLE sf AS
    SELECT station, slot, y,
      sum(y)   OVER (PARTITION BY station ORDER BY slot RANGE BETWEEN 300 PRECEDING AND 300 PRECEDING) AS lag1,
      sum(y)   OVER (PARTITION BY station ORDER BY slot RANGE BETWEEN 600 PRECEDING AND 600 PRECEDING) AS lag2,
      sum(y)   OVER (PARTITION BY station ORDER BY slot RANGE BETWEEN 600 PRECEDING AND CURRENT ROW) AS s3,
      sum(y)   OVER (PARTITION BY station ORDER BY slot RANGE BETWEEN 1500 PRECEDING AND CURRENT ROW) AS s6,
      sum(y)   OVER (PARTITION BY station ORDER BY slot RANGE BETWEEN 3300 PRECEDING AND CURRENT ROW) AS s12,
      max(y)   OVER (PARTITION BY station ORDER BY slot RANGE BETWEEN 3300 PRECEDING AND CURRENT ROW) AS max12,
      count(y) OVER (PARTITION BY station ORDER BY slot RANGE BETWEEN 3300 PRECEDING AND CURRENT ROW) AS c12,
      sum(y)   OVER (PARTITION BY station ORDER BY slot RANGE BETWEEN 10500 PRECEDING AND CURRENT ROW) AS s36,
      count(y) OVER (PARTITION BY station ORDER BY slot RANGE BETWEEN 10500 PRECEDING AND CURRENT ROW) AS c36,
      sum(y)   OVER (PARTITION BY station ORDER BY slot RANGE BETWEEN 300 FOLLOWING AND 1800 FOLLOWING) AS target,
      count(y) OVER (PARTITION BY station ORDER BY slot RANGE BETWEEN 300 FOLLOWING AND 1800 FOLLOWING) AS fc
    FROM obs
    """)


def neighbour_map(con, year):
    """K nearest other stations among those active in `year`, with static geometry."""
    rows = con.execute(f"""
      SELECT station, mode(lat) AS lat, mode(lon) AS lon FROM obs
      WHERE year(to_timestamp(slot) AT TIME ZONE 'Asia/Singapore') = {year}
      GROUP BY station ORDER BY station
    """).fetchall()
    st = np.array([r[0] for r in rows])
    lat = np.array([r[1] for r in rows]); lon = np.array([r[2] for r in rows])
    d = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    np.fill_diagonal(d, np.inf)
    out = []
    km_per_deg = 111.32
    for i, s in enumerate(st):
        order = np.lexsort((st, d[i]))[:K]
        for k, j in enumerate(order, start=1):
            dx = (lon[j] - lon[i]) * km_per_deg * math.cos(math.radians(lat[i]))
            dy = (lat[j] - lat[i]) * km_per_deg
            out.append((s, k, st[j], float(d[i, j]), float(dx), float(dy)))
    con.execute("DROP TABLE IF EXISTS nb")
    con.execute("CREATE TABLE nb (station VARCHAR, k INTEGER, nb_station VARCHAR, dist DOUBLE, dx DOUBLE, dy DOUBLE)")
    con.executemany("INSERT INTO nb VALUES (?, ?, ?, ?, ?, ?)", out)
    return len(st)


def build_year(con, year):
    n_st = neighbour_map(con, year)
    lo = f"epoch(TIMESTAMPTZ '{year}-01-01 00:00:00+08')"
    hi = f"epoch(TIMESTAMPTZ '{year + 1}-01-01 00:00:00+08')"
    select_nb, joins = [], []
    for k in range(1, K + 1):
        joins.append(f"""
          LEFT JOIN nb nb{k} ON nb{k}.station = t.station AND nb{k}.k = {k}
          LEFT JOIN sf n{k} ON n{k}.station = nb{k}.nb_station AND n{k}.slot = t.slot - 300""")
        select_nb.append(f"""
          n{k}.y AS nb{k}_y1, n{k}.s3 AS nb{k}_s3, n{k}.s12 AS nb{k}_s12,
          CAST(n{k}.c12 = 12 AS INTEGER) AS nb{k}_c12ok,
          CAST(n{k}.y IS NOT NULL AS INTEGER) AS nb{k}_avail,
          nb{k}.dist AS nb{k}_dist, nb{k}.dx AS nb{k}_dx, nb{k}.dy AS nb{k}_dy""")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"year={year}.parquet"
    con.execute(f"""
    COPY (
      SELECT t.station, t.slot, o.lat, o.lon,
             t.y, t.lag1, t.lag2, t.s3, t.s6, t.s12, t.max12, t.s36, t.c36,
             {', '.join(select_nb)},
             t.target
      FROM sf t
      JOIN obs o ON o.station = t.station AND o.slot = t.slot
      {' '.join(joins)}
      WHERE t.slot >= {lo} AND t.slot < {hi} AND t.c12 = 12 AND t.fc = 6
      ORDER BY t.slot, t.station
    ) TO '{path}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    n = con.execute(f"SELECT count(*), avg(CAST(target > 0 AS DOUBLE)), avg(CAST(target > 1 AS DOUBLE)) FROM '{path}'").fetchone()
    print(f"{year}: stations={n_st} rows={n[0]:,} P(y>0)={n[1]:.4f} P(y>1mm)={n[2]:.4f}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int, default=list(range(2017, 2025)))
    ap.add_argument("--memory", default="14GB")
    args = ap.parse_args()
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))
    con.execute(f"SET memory_limit='{args.memory}'; SET threads=8; SET TimeZone='Asia/Singapore'")
    con.execute(f"SET temp_directory='{DB.parent / 'duck_tmp'}'")
    load_slots(con, args.years)
    station_features(con)
    for y in args.years:
        build_year(con, y)


if __name__ == "__main__":
    main()
