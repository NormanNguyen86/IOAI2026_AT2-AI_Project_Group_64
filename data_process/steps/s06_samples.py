"""Step 6: the shared master table (shared/samples.csv): catchment_id, issue_utc, label, split.

A row is kept only if:
  - the 72 radar hours (issue-71h ... issue) all pass radar QC (common.radar_good: scans, coverage, fill code, stuck values),
  - the gauge has level data at the issue hour and in every hour of (issue, issue+6h],
  - the gauge is not already in flood at the issue time (onset <= issue < end),
  - the issue time is not within gap_hours of a change of split (holdout rows always kept).
"""
import numpy as np
import pandas as pd
from common import CFG, INTERIM, SHARED, catchments, log, split_of, utc, radar_good

STEP = "s06"


def main():
    hist, hor = CFG["time"]["history_hours"], CFG["time"]["horizon_hours"]
    gap, R = CFG["split"]["gap_hours"], CFG["radar"]
    hours = pd.date_range(utc(CFG["period"]["start_utc"]), utc(CFG["period"]["end_utc"]), freq="1h")
    issue = hours[hist - 1: len(hours) - hor]
    split = split_of(issue)
    change = issue[1:][split[1:] != split[:-1]]
    near = np.zeros(len(issue), bool)
    for c in change:
        near |= np.abs((issue - c) / pd.Timedelta(hours=1)) < gap
    near &= split != "holdout"

    cat = catchments()
    ev = pd.read_csv(SHARED / "events.csv", dtype={"catchment_id": str}, parse_dates=["onset_utc", "end_utc"])
    out, stats = [], []
    for c in cat.itertuples():
        rad = pd.read_csv(INTERIM / "radar" / f"radar{c.radar_id}_hourly.csv", dtype={"catchment_id": str})
        rad = rad[rad.catchment_id == c.catchment_id].set_index(pd.to_datetime(rad.hour_end_utc[rad.catchment_id == c.catchment_id], utc=True))
        rad = rad.sort_index()
        good = radar_good(rad).reindex(hours, fill_value=False).to_numpy()
        hist_ok = pd.Series(good).rolling(hist).min().to_numpy()[hist - 1: len(hours) - hor] == 1

        lv = pd.read_csv(INTERIM / "levels" / f"{c.catchment_id}.csv", index_col=0, parse_dates=True).level_max_m.reindex(hours)
        has = lv.notna().to_numpy()
        lab_ok = has[hist - 1: len(hours) - hor].copy()
        for k in range(1, hor + 1):
            lab_ok &= has[hist - 1 + k: len(hours) - hor + k]

        label = np.zeros(len(issue), np.int8); in_flood = np.zeros(len(issue), bool)
        for e in ev[ev.catchment_id == c.catchment_id].itertuples():
            label[(issue >= e.onset_utc - pd.Timedelta(hours=hor)) & (issue < e.onset_utc)] = 1
            in_flood |= (issue >= e.onset_utc) & (issue < e.end_utc)

        keep = hist_ok & lab_ok & ~in_flood & ~near & (split != "")
        out.append(pd.DataFrame({"catchment_id": c.catchment_id, "issue_utc": issue[keep].strftime("%Y-%m-%dT%H:%M:%SZ"),
                                 "label": label[keep], "split": split[keep]}))
        stats.append(dict(catchment_id=c.catchment_id, candidate=len(issue), radar_gap=int((~hist_ok).sum()),
                          level_gap=int((~lab_ok).sum()), in_flood=int(in_flood.sum()), kept=int(keep.sum())))
    s = pd.concat(out)
    s.to_csv(SHARED / "samples.csv", index=False)
    pd.DataFrame(stats).to_csv(INTERIM / "samples_filter_stats.csv", index=False)
    log(STEP, f"{len(s):,} samples\n" + s.groupby(["split", "label"]).size().unstack(fill_value=0).to_string())


if __name__ == "__main__":
    main()
