"""Candidate B: turn the shared master table into LSTM-ready arrays.

Reads (shared):   ../shared_data/config.json, samples.csv, catchments.csv
Reads (B only):   b_hourly_rain.csv   catchment_id, hour_end_utc, rain_mean, rain_max, rain_p90, rain_frac_ge2
                  b_soil_daily.csv    catchment_id, date, soil_upper_mm, soil_lower_mm   (AWRA-L, catchment mean)
                  b_static.csv        catchment_id + static attributes (CAMELS-AUS)
Writes:           b_dataset.npz       X_dyn (N, 72, F_dyn), X_static (N, F_static), y (N,), split, catchment_id, issue_utc
                  b_dataset_preview.csv   the 72 rows of the first positive sample, for checking by eye

Usage: python build_b_dataset.py
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent / "shared_data"
CFG = json.loads((SHARED / "config.json").read_text())
HIST = CFG["time"]["history_hours"]
LOCAL_OFFSET_H = 10            # AWRA-L days follow local (AEST) dates

RAIN = ["rain_mean", "rain_max", "rain_p90", "rain_frac_ge2"]
SOIL = ["soil_upper_mm", "soil_lower_mm"]
STATIC = ["catchment_area", "elev_mean", "relief", "mean_slope_pct", "ksat", "claya", "sanda",
          "solpawhc", "lc35_urbanar", "prop_forested", "strdensity", "elongratio", "p_mean"]


def main():
    s = pd.read_csv(SHARED / CFG["files"]["samples"], dtype={"catchment_id": str})
    s["issue_utc"] = pd.to_datetime(s.issue_utc, utc=True)
    rain = pd.read_csv(HERE / "b_hourly_rain.csv", dtype={"catchment_id": str})
    rain["hour_end_utc"] = pd.to_datetime(rain.hour_end_utc, utc=True)
    soil = pd.read_csv(HERE / "b_soil_daily.csv", dtype={"catchment_id": str}, parse_dates=["date"])
    stat = pd.read_csv(HERE / "b_static.csv", dtype={"catchment_id": str}).set_index("catchment_id")

    N, F = len(s), len(RAIN) + len(SOIL)
    X = np.full((N, HIST, F), np.nan, np.float32)
    XS = stat.loc[s.catchment_id, STATIC].to_numpy(np.float32)
    row = 0
    for cid, grp in s.groupby("catchment_id", sort=False):
        r = rain[rain.catchment_id == cid].set_index("hour_end_utc")[RAIN]
        so = soil[soil.catchment_id == cid].set_index("date")[SOIL]
        for i, t in zip(grp.index, grp.issue_utc):
            stamps = pd.date_range(end=t, periods=HIST, freq="1h")          # issue-71h ... issue
            X[i, :, :len(RAIN)] = r.reindex(stamps).to_numpy()
            prev_day = (t + pd.Timedelta(hours=LOCAL_OFFSET_H)).normalize().tz_localize(None) - pd.Timedelta(days=1)
            X[i, :, len(RAIN):] = so.loc[prev_day].to_numpy()               # same value for all 72 steps
            row += 1

    bad = np.isnan(X).any(axis=(1, 2))
    if bad.any():
        print(f"WARNING: {bad.sum()} samples have gaps; they are dropped")
    keep = ~bad
    np.savez_compressed(HERE / "b_dataset.npz",
                        X_dyn=X[keep], X_static=XS[keep], y=s.label.to_numpy(np.int8)[keep],
                        split=s.split.to_numpy()[keep], catchment_id=s.catchment_id.to_numpy()[keep],
                        issue_utc=s.issue_utc.dt.strftime("%Y-%m-%dT%H:%M:%SZ").to_numpy()[keep],
                        dyn_features=np.array(RAIN + SOIL), static_features=np.array(STATIC))

    k = int(np.flatnonzero((s.label.to_numpy() == 1) & keep)[0])
    prev = pd.DataFrame(X[k], columns=RAIN + SOIL)
    prev.insert(0, "hour_end_utc", pd.date_range(end=s.issue_utc[k], periods=HIST, freq="1h").strftime("%Y-%m-%dT%H:%MZ"))
    prev.insert(0, "issue_utc", s.issue_utc[k].strftime("%Y-%m-%dT%H:%MZ"))
    prev.insert(0, "catchment_id", s.catchment_id[k])
    prev.to_csv(HERE / "b_dataset_preview.csv", index=False)

    print(f"X_dyn {X[keep].shape}  X_static {XS[keep].shape}  positives {int(s.label[keep].sum())}")
    print(pd.crosstab(s.split[keep], s.label[keep]))


if __name__ == "__main__":
    main()
