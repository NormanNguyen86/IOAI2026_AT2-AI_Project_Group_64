"""Step 2: download river level for each outlet gauge (BoM Water Data Online, KiWIS API).

Raw:     data/raw/levels/<awrc_id>/<year>.json   exactly as returned by BoM (timestamps carry +10:00)
Interim: data/interim/levels/<catchment_id>.csv  hour_end_utc, level_max_m (maximum reading in (h-1h, h])
Gauges without the configured series are dropped from shared/catchments.csv (and logged).
"""
import json
import pandas as pd
from common import CFG, RAW, INTERIM, SHARED, download, catchments, log, utc

STEP = "s02"
K = CFG["urls"]["kiwis"]


def kiwis(params, save_to=None):
    p = {"service": "kisters", "type": "QueryServices", "format": "json", **params}
    body = download(K, params=p, save_to=save_to, step=STEP)
    return json.loads(body)


def main():
    cat = catchments()
    start, end = utc(CFG["period"]["start_utc"]), utc(CFG["period"]["end_utc"])
    series = CFG["label"]["level_series"]
    (INTERIM / "levels").mkdir(exist_ok=True)
    keep = []
    for c in cat.itertuples():
        lst = kiwis({"request": "getTimeseriesList", "station_no": c.awrc_id,
                     "parametertype_name": "Water Course Level", "ts_name": series})
        if len(lst) < 2:
            log(STEP, f"{c.catchment_id}: no '{series}' series -> dropped"); continue
        ts_id = lst[1][3]
        frames = []
        for y in range(start.year, end.year + 1):
            f = RAW / "levels" / str(c.awrc_id) / f"{y}.json"
            if f.exists():
                j = json.loads(f.read_text())
            else:
                j = kiwis({"request": "getTimeseriesValues", "ts_id": ts_id, "returnfields": "Timestamp,Value,Quality Code",
                           "from": f"{y}-01-01T00:00:00", "to": f"{y}-12-31T23:59:59"}, save_to=f)
            frames.append(pd.DataFrame(j[0]["data"], columns=["t", "v", "q"]))
        df = pd.concat(frames).dropna(subset=["v"])
        s = pd.Series(df.v.values, index=pd.to_datetime(df.t, utc=True)).sort_index()
        h = s.resample("1h", closed="right", label="right").max()      # hour-ending maximum
        h = h[(h.index >= start) & (h.index <= end)]
        out = h.rename("level_max_m").to_frame()
        out.index.name = "hour_end_utc"
        out.to_csv(INTERIM / "levels" / f"{c.catchment_id}.csv")
        log(STEP, f"{c.catchment_id}: {len(s):,} readings -> {out.level_max_m.notna().sum():,} hours")
        keep.append(c.catchment_id)
    cat[cat.catchment_id.isin(keep)].to_csv(SHARED / "catchments.csv", index=False)


if __name__ == "__main__":
    main()
