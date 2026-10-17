"""Find flood onsets in one gauge's river level series and add them to events.csv.

Usage:
    python scripts/detect_events.py --catchment-id 58200 --level level_203014.csv
    (optional) --threshold 3.2   overrides threshold_m in catchments.csv
    (optional) --utc-offset 10   hours to subtract from the file's timestamps (Water Data Online
                                  uses local standard time, AEST = UTC+10; check this once)

level CSV: two columns, timestamp and value (m). Extra header lines from the export
should be removed first, or set --skiprows.
"""
import argparse
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config.json").read_text())


def hourly_max(level_csv, utc_offset, skiprows):
    s = pd.read_csv(level_csv, skiprows=skiprows, header=0, names=["t", "v"])
    s["t"] = pd.to_datetime(s["t"]) - pd.Timedelta(hours=utc_offset)
    s = s.dropna().set_index("t")["v"]
    # hour-ending bins: a reading at 09:40 belongs to the hour stamped 10:00
    return s.resample("1h", closed="right", label="right").max()


def find_events(level, threshold, min_below):
    above = level > threshold
    events, below_run, start = [], min_below, None
    for t, a in above.items():
        if pd.isna(level[t]):
            continue
        if start is None and a and below_run >= min_below:
            start = t
        if start is not None and not a:
            events.append((start, t))
            start = None
        below_run = 0 if a else below_run + 1
    if start is not None:
        events.append((start, level.index[-1]))
    return events


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--catchment-id", required=True)
    p.add_argument("--level", required=True)
    p.add_argument("--threshold", type=float)
    p.add_argument("--utc-offset", type=float, default=10)
    p.add_argument("--skiprows", type=int, default=0)
    a = p.parse_args()

    cat = pd.read_csv(ROOT / CFG["files"]["catchments"], dtype={"catchment_id": str})
    row = cat[cat.catchment_id == a.catchment_id]
    thr = a.threshold if a.threshold is not None else float(row.threshold_m.iloc[0])

    level = hourly_max(a.level, a.utc_offset, a.skiprows)
    new = pd.DataFrame(find_events(level, thr, CFG["label"]["onset_min_hours_below"]),
                       columns=["onset_utc", "end_utc"])
    new.insert(0, "catchment_id", a.catchment_id)
    for c in ("onset_utc", "end_utc"):
        new[c] = new[c].dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    ev_path = ROOT / CFG["files"]["events"]
    ev = pd.read_csv(ev_path, dtype={"catchment_id": str})
    ev = ev[ev.catchment_id != a.catchment_id]          # re-running replaces this gauge
    pd.concat([ev, new]).sort_values(["catchment_id", "onset_utc"]).to_csv(ev_path, index=False)
    print(f"{a.catchment_id}: {len(new)} events above {thr} m written to {ev_path.name}")


if __name__ == "__main__":
    main()
