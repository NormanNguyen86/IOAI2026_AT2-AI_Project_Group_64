"""Build samples.csv (the shared master table) from config.json, catchments.csv,
events.csv and, if present, missing_hours.csv.

Usage:
    python scripts/build_samples.py

Output columns: catchment_id, issue_utc, label, split
Rows that must not be scored are simply left out:
  - issue times while the gauge is already in flood (onset <= t < end)
  - issue times whose 72 h history contains a missing radar hour
  - issue times within gap_hours of a change of split (so no input or label window is shared)
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config.json").read_text())
H = pd.Timedelta(hours=1)


def utc(x):
    return pd.to_datetime(x, utc=True)


def split_of(t, sp):
    hold = (t >= utc(sp["holdout"]["start_utc"])) & (t <= utc(sp["holdout"]["end_utc"]))
    year = t.year
    s = np.where(np.isin(year, sp["val_years"]), "val",
                 np.where(np.isin(year, sp["test_years"]), "test", "train"))
    return np.where(hold, "holdout", s)


def main():
    hist, hor = CFG["time"]["history_hours"], CFG["time"]["horizon_hours"]
    sp, gap = CFG["split"], CFG["split"]["gap_hours"]
    f = CFG["files"]

    cats = pd.read_csv(ROOT / f["catchments"], dtype={"catchment_id": str}).catchment_id
    ev = pd.read_csv(ROOT / f["events"], dtype={"catchment_id": str})
    ev["onset_utc"], ev["end_utc"] = utc(ev.onset_utc), utc(ev.end_utc)
    miss_path = ROOT / f["missing_hours"]
    miss = (pd.read_csv(miss_path, dtype={"catchment_id": str}) if miss_path.exists()
            else pd.DataFrame(columns=["catchment_id", "hour_end_utc"]))
    miss["hour_end_utc"] = utc(miss.hour_end_utc)

    # first issue time needs a full history inside the period
    times = pd.date_range(utc(CFG["period"]["start_utc"]) + hist * H,
                          utc(CFG["period"]["end_utc"]) - hor * H, freq="1h")
    split = pd.Series(split_of(times, sp), index=times)
    change = times[1:][split.values[1:] != split.values[:-1]]
    near = np.zeros(len(times), bool)
    for c in change:
        near |= (abs(times - c) < gap * H) & (split.values != "holdout")

    out = []
    for cid in cats:
        df = pd.DataFrame({"issue_utc": times, "split": split.values, "keep": ~near})
        df["label"] = 0
        for _, e in ev[ev.catchment_id == cid].iterrows():
            df.loc[(df.issue_utc >= e.onset_utc - hor * H) & (df.issue_utc < e.onset_utc), "label"] = 1
            df.loc[(df.issue_utc >= e.onset_utc) & (df.issue_utc < e.end_utc), "keep"] = False
        for m in miss[miss.catchment_id == cid].hour_end_utc:
            df.loc[(df.issue_utc >= m) & (df.issue_utc < m + hist * H), "keep"] = False
        df = df[df.keep]
        df.insert(0, "catchment_id", cid)
        out.append(df[["catchment_id", "issue_utc", "label", "split"]])

    s = pd.concat(out)
    s["issue_utc"] = s.issue_utc.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    s.to_csv(ROOT / f["samples"], index=False)
    print(s.groupby(["split", "label"]).size().unstack(fill_value=0))
    print(f"wrote {len(s):,} rows to {f['samples']}")


if __name__ == "__main__":
    main()
