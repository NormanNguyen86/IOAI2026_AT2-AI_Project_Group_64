"""Download and summarise B's raw inputs for a full study period.

Run this on a computer with normal internet access (it reads public BoM / NCI services; no account needed):

    pip install requests numpy pandas xarray netCDF4
    python fetch_b_inputs.py --start 2019-01-01 --end 2025-12-31

What it does, per catchment in ../shared_data/catchments.csv:
  1. River level  -> levels/level_<id>.csv   hourly mean, UTC        (BoM Water Data Online, KiWIS API)
  2. Radar rain   -> b_hourly_rain.csv        catchment stats per UTC hour (Rainfields3 'prcp-m15', NCI THREDDS)
  3. Soil water   -> b_soil_daily.csv         AWRA-L s0 / ss, catchment mean per day (NCI THREDDS NetcdfSubset)

Inputs it needs next to this script:
  masks_radar<ID>.npz   one boolean 512x512 array per catchment on that radar's grid (built from boundaries)
  awra_cells.json       {catchment_id: {"bbox": [south, north, west, east], "cells": [[lat, lon], ...]}}
Radar days are processed one at a time and not kept, so disk use stays small.
"""
import argparse, io, json, zipfile, tempfile, os
from pathlib import Path
import numpy as np
import pandas as pd
import requests
import xarray as xr

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent / "shared_data"
KIWIS = "https://www.bom.gov.au/waterdata/services"
THREDDS = "https://thredds.nci.org.au/thredds"
S = requests.Session()


# ---------- 1. river level ----------
def kiwis(**params):
    p = dict(service="kisters", type="QueryServices", format="json", **params)
    r = S.get(KIWIS, params=p, timeout=120); r.raise_for_status(); return r.json()


def fetch_level(station_no, start, end):
    ts = kiwis(request="getTimeseriesList", station_no=station_no,
               parametertype_name="Water Course Level", ts_name="DMQaQc.Merged.HourlyMean.HR")
    ts_id = ts[1][3]
    frames = []
    for y in range(start.year, end.year + 1):
        j = kiwis(request="getTimeseriesValues", ts_id=ts_id, returnfields="Timestamp,Value",
                  **{"from": f"{y}-01-01T00:00:00", "to": f"{y}-12-31T23:00:00"})
        frames.append(pd.DataFrame(j[0]["data"], columns=["t", "level_m"]))
    df = pd.concat(frames)
    df["time_utc"] = pd.to_datetime(df.t, utc=True).dt.tz_localize(None)   # stamps carry +10:00
    return df[["time_utc", "level_m"]]


# ---------- 2. radar ----------
def radar_day(radar, day, masks):
    """Return {(cid, hour_end): (sum array, bad array, n)} partial sums for one UTC day file."""
    url = f"{THREDDS}/fileServer/rq0/rainfields3/{radar}/{day:%Y}/prcp-m15/{radar}_{day:%Y%m%d}.prcp-m15.zip"
    r = S.get(url, timeout=300)
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    out = {}
    with zipfile.ZipFile(io.BytesIO(r.content)) as z, tempfile.TemporaryDirectory() as td:
        for name in sorted(n for n in z.namelist() if n.endswith(".nc")):
            path = z.extract(name, td)
            with xr.open_dataset(path) as ds:
                p = ds.precipitation.values                      # mm per 15 min; NaN = no data
                vt = pd.Timestamp(ds.valid_time.values)          # end of the 15 minutes (UTC)
            os.remove(path)
            hour_end = vt.ceil("1h")
            for cid, m in masks.items():
                v = p[m]
                key = (cid, hour_end)
                s, b, n = out.get(key, (np.zeros(v.size), np.zeros(v.size, bool), 0))
                out[key] = (s + np.nan_to_num(v), b | np.isnan(v), n + 1)
    return out


def summarise(cid, hour_end, s, b, n):
    ok = s[~b]
    cov = ok.size / s.size
    if ok.size == 0:
        return dict(catchment_id=cid, hour_end_utc=hour_end, n15=n, coverage=0.0)
    return dict(catchment_id=cid, hour_end_utc=hour_end, n15=n, coverage=round(cov, 3),
                rain_mean=round(ok.mean(), 2), rain_max=round(ok.max(), 2),
                rain_p90=round(float(np.sort(ok)[min(ok.size - 1, int(0.9 * ok.size))]), 2),
                rain_frac_ge2=round((ok >= 2).mean(), 3))


def fetch_radar(radar, masks, start, end):
    pending, rows = {}, []
    for day in pd.date_range(start, end, freq="D"):
        for k, (s, b, n) in radar_day(radar, day, masks).items():
            if k in pending:
                s0, b0, n0 = pending[k]; s, b, n = s0 + s, b0 | b, n0 + n
            pending[k] = (s, b, n)
        for k in [k for k in pending if k[1] <= day]:            # hours ending by 00:00 of this day are complete
            rows.append(summarise(k[0], k[1], *pending.pop(k)))
        print(f"radar {radar} {day:%Y-%m-%d} done", flush=True)
    rows += [summarise(k[0], k[1], *v) for k, v in pending.items()]
    return pd.DataFrame(rows)


# ---------- 3. soil ----------
def fetch_soil(cid, info, var, year):
    s, n, w, e = info["bbox"]
    url = (f"{THREDDS}/ncss/grid/iu04/australian-water-outlook/historical/v1/AWRALv7/{var}_{year}.nc"
           f"?var={var}&north={n}&south={s}&west={w}&east={e}"
           f"&time_start={year}-01-01T00:00:00Z&time_end={year}-12-31T00:00:00Z&accept=netcdf4")
    r = S.get(url, timeout=300); r.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as f:
        f.write(r.content); path = f.name
    with xr.open_dataset(path) as ds:
        vals = [ds[var].sel(latitude=la, longitude=lo, method="nearest") for la, lo in info["cells"]]
        mean = xr.concat(vals, "cell").mean("cell").to_series()
    os.remove(path)
    return mean.rename(var)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--radar", default="28")
    ap.add_argument("--skip", nargs="*", default=[], choices=["level", "radar", "soil"])
    a = ap.parse_args()
    start, end = pd.Timestamp(a.start), pd.Timestamp(a.end)
    cats = pd.read_csv(SHARED / "catchments.csv", dtype={"catchment_id": str, "awrc_id": str})

    if "level" not in a.skip:
        (HERE / "levels").mkdir(exist_ok=True)
        for _, c in cats.iterrows():
            fetch_level(c.awrc_id, start, end).to_csv(HERE / "levels" / f"level_{c.catchment_id}.csv", index=False)
            print("level", c.catchment_id, "done")

    if "radar" not in a.skip:
        masks = dict(np.load(HERE / f"masks_radar{a.radar}.npz"))
        masks = {k: v for k, v in masks.items() if k in set(cats.catchment_id)}
        fetch_radar(a.radar, masks, start - pd.Timedelta(days=3), end).to_csv(HERE / "b_hourly_rain.csv", index=False)

    if "soil" not in a.skip:
        cells = json.loads((HERE / "awra_cells.json").read_text()); frames = []
        for cid, info in cells.items():
            for y in range(start.year, end.year + 1):
                d = pd.concat([fetch_soil(cid, info, v, y) for v in ("s0", "ss")], axis=1)
                d.columns = ["soil_upper_mm", "soil_lower_mm"]; d.index.name = "date"
                frames.append(d.reset_index().assign(catchment_id=cid))
            print("soil", cid, "done")
        pd.concat(frames)[["catchment_id", "date", "soil_upper_mm", "soil_lower_mm"]].to_csv(HERE / "b_soil_daily.csv", index=False)


if __name__ == "__main__":
    main()
