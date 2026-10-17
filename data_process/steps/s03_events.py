"""Step 3: flood thresholds and flood events per gauge.

Threshold: config label.manual_thresholds[catchment_id] if given (e.g. official minor flood level),
           else the configured percentile of hourly maximum level over TRAIN hours only (holdout excluded).
Event:     onset = first hour above threshold after >= onset_min_hours_below hours below; end = first hour back below.
           A rise after fewer hours below is merged into the previous event.
Writes: shared/catchments.csv (threshold_m, threshold_type), shared/events.csv
"""
import numpy as np
import pandas as pd
from common import CFG, INTERIM, SHARED, catchments, log, split_of

STEP = "s03"


def find_events(level, thr, min_below):
    """A rise above thr after >= min_below hours below starts a new event; a rise after fewer
    hours below re-opens the previous event (so those hours are excluded, never labelled 0)."""
    ev, below, start = [], min_below, None
    for t, v in level.items():
        if np.isnan(v):
            continue
        above = v > thr
        if start is None and above:
            if below >= min_below or not ev:
                start = t
            else:
                start = ev.pop()[0]                       # merge with the previous event
        if start is not None and not above:
            ev.append((start, t)); start = None
        below = 0 if above else below + 1
    if start is not None:
        ev.append((start, level.index[-1]))
    return ev


def main():
    cat = catchments()
    cat["threshold_m"] = cat["threshold_m"].astype(object)
    cat["threshold_type"] = cat["threshold_type"].astype(object)
    L = CFG["label"]
    rows = []
    for i, c in cat.iterrows():
        lv = pd.read_csv(INTERIM / "levels" / f"{c.catchment_id}.csv", index_col=0, parse_dates=True).level_max_m
        if c.catchment_id in L["manual_thresholds"]:
            thr, kind = float(L["manual_thresholds"][c.catchment_id]), "manual"
        else:
            train = lv[split_of(lv.index) == "train"].dropna()
            thr, kind = float(np.percentile(train, L["fallback_percentile"])), f"p{L['fallback_percentile']}_train"
        cat.loc[i, ["threshold_m", "threshold_type"]] = [round(thr, 3), kind]
        ev = find_events(lv, thr, L["onset_min_hours_below"])
        rows += [(c.catchment_id, a.strftime("%Y-%m-%dT%H:%M:%SZ"), b.strftime("%Y-%m-%dT%H:%M:%SZ")) for a, b in ev]
        log(STEP, f"{c.catchment_id}: threshold {thr:.3f} m ({kind}), {len(ev)} events")
    cat.to_csv(SHARED / "catchments.csv", index=False)
    pd.DataFrame(rows, columns=["catchment_id", "onset_utc", "end_utc"]).to_csv(SHARED / "events.csv", index=False)


if __name__ == "__main__":
    main()
