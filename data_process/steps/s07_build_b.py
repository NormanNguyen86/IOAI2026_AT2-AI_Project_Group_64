"""Step 7 (Candidate B only): one hourly feature table per catchment + checks + optional arrays.

Writes data/processed/b/dynamic_hourly.parquet with columns catchment_id, hour_end_utc and the
dynamic features in config b_features.dynamic. Soil for hour h = AWRA-L value of the local day
before h's local date (so it is always complete before h). Static features are in static.csv (step 1).
Then checks every master-table row with WindowDataset and writes a preview of one positive window.

Usage: python steps/s07_build_b.py [--npz val test holdout]   (also save those splits as .npz arrays)
"""
import argparse
import numpy as np
import pandas as pd
from common import CFG, INTERIM, PROCESSED, catchments, log, utc, radar_good

STEP = "s07"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--npz", nargs="*", default=[]); a = ap.parse_args()
    B = PROCESSED / "b"; B.mkdir(exist_ok=True)
    hours = pd.date_range(utc(CFG["period"]["start_utc"]), utc(CFG["period"]["end_utc"]), freq="1h")
    soil = pd.read_csv(INTERIM / "soil_daily.csv", dtype={"catchment_id": str}, parse_dates=["date"])
    R, off = CFG["radar"], pd.Timedelta(hours=CFG["soil"]["local_utc_offset_hours"])
    soil_cols = list(CFG["soil"]["variables"].values())
    frames = []
    for c in catchments().itertuples():
        rad = pd.read_csv(INTERIM / "radar" / f"radar{c.radar_id}_hourly.csv", dtype={"catchment_id": str})
        rad = rad[rad.catchment_id == c.catchment_id]
        rad.index = pd.to_datetime(rad.hour_end_utc, utc=True)
        rad = rad.sort_index()
        good = radar_good(rad)
        d = rad.loc[good, ["rain_mean", "rain_max", "rain_p90", "rain_frac_heavy"]].reindex(hours)
        prev_day = ((hours + off).tz_localize(None).normalize() - pd.Timedelta(days=1))
        so = soil[soil.catchment_id == c.catchment_id].set_index("date")[soil_cols]
        d[soil_cols] = so.reindex(prev_day).to_numpy()
        d.insert(0, "catchment_id", c.catchment_id); d.index.name = "hour_end_utc"
        frames.append(d.reset_index())
    dyn = pd.concat(frames)[["catchment_id", "hour_end_utc"] + CFG["b_features"]["dynamic"]]
    dyn.to_parquet(B / "dynamic_hourly.parquet", index=False)
    log(STEP, f"dynamic_hourly.parquet: {len(dyn):,} rows")

    import sys; sys.path.insert(0, str(PROCESSED.parents[1] / "steps"))
    from b_dataset import WindowDataset
    ds = WindowDataset()
    # NaN check without stacking every window: rolling "any NaN" over 72 h, read at each window end
    bad = np.zeros(len(ds), bool)
    for cid, arr in ds.series.items():
        flag = pd.Series(np.isnan(arr).any(axis=1)).rolling(ds.hist, min_periods=1).max().to_numpy() > 0
        m = (ds.samples.catchment_id == cid).to_numpy()
        bad[m] = flag[ds.end_idx[m]] | np.isnan(ds.static[cid]).any()
    Y = ds.samples.label.to_numpy()
    log(STEP, f"{len(ds):,} windows of {ds.hist} x {len(ds.dyn_names)} + {len(ds.static_names)} static; "
              f"windows with NaN: {int(bad.sum())}; positives: {int(Y.sum())}")
    k = int(np.flatnonzero(Y == 1)[0]) if Y.any() else 0
    s = ds.samples.iloc[k]
    prev = pd.DataFrame(ds[k][0], columns=ds.dyn_names)
    prev.insert(0, "hour_end_utc", pd.date_range(end=pd.Timestamp(s.issue_utc), periods=ds.hist, freq="1h").strftime("%Y-%m-%dT%H:%MZ"))
    prev.insert(0, "issue_utc", s.issue_utc); prev.insert(0, "catchment_id", s.catchment_id); prev["label"] = s.label
    prev.to_csv(B / "preview_one_window.csv", index=False)
    for sp in a.npz:
        d = WindowDataset(split=sp)
        X, XS, Yb = d.arrays()
        np.savez_compressed(B / f"windows_{sp}.npz", X_dyn=X, X_static=XS, y=Yb,
                            catchment_id=d.samples.catchment_id.to_numpy(), issue_utc=d.samples.issue_utc.to_numpy(),
                            dyn_features=np.array(d.dyn_names), static_features=np.array(d.static_names))
        log(STEP, f"windows_{sp}.npz: {len(d):,} windows")


if __name__ == "__main__":
    main()
