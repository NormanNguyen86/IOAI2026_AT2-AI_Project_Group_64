"""Step 4: radar rain per catchment per UTC hour (Rainfields3 'prcp-m15', NCI THREDDS).

Each daily zip holds 96 files of 15-min accumulation (mm), stamped with the END of the 15 minutes.
A file stamped t goes to the hour ending ceil(t). Hour stats over mask cells (cells with any missing
15-min value in that hour are excluded): rain_mean, rain_max, rain_p90, rain_frac_heavy, coverage, n15.

Resumable: progress is saved after every day in data/interim/radar/radar<ID>_state.pkl.
Writes: data/interim/radar/radar<ID>_hourly.csv
Usage:  python steps/s04_radar.py [--workers 4]
"""
import argparse, io, pickle, zipfile
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import netCDF4
from common import CFG, RAW, INTERIM, SHARED, download, catchments, log, utc

STEP = "s04"
R = CFG["radar"]


def fetch(rid, day):
    url = f"{CFG['urls']['thredds']}/fileServer/rq0/rainfields3/{rid}/{day:%Y}/{R['product']}/{rid}_{day:%Y%m%d}.{R['product']}.zip"
    save = RAW / "radar" / rid / f"{day:%Y}" / url.rsplit("/", 1)[1] if R["keep_raw_zips"] else None
    if save and save.exists():
        return save.read_bytes()
    return download(url, save_to=save, step=STEP)


def scans(body):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        for name in sorted(n for n in z.namelist() if n.endswith(".nc")):
            with netCDF4.Dataset("mem", memory=z.read(name)) as ds:
                vt = pd.Timestamp(float(ds["valid_time"][:]), unit="s", tz="UTC")
                p = ds["precipitation"][:].filled(np.nan).ravel()
            yield vt, p


def summarise(cid, h, s, bad, n):
    ok = s[~bad]
    row = dict(catchment_id=cid, hour_end_utc=h.strftime("%Y-%m-%dT%H:%M:%SZ"), n15=n,
               coverage=round(ok.size / s.size, 3))
    if ok.size:
        row.update(rain_mean=round(float(ok.mean()), 3), rain_max=round(float(ok.max()), 2),
                   rain_p90=round(float(np.percentile(ok, 90)), 2),
                   rain_frac_heavy=round(float((ok >= R["heavy_mm_per_hour"]).mean()), 3))
    return row


def run(rid, idx, workers):
    out_csv = INTERIM / "radar" / f"radar{rid}_hourly.csv"
    state_f = INTERIM / "radar" / f"radar{rid}_state.pkl"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    days = pd.date_range(utc(CFG["period"]["start_utc"]).normalize(), utc(CFG["period"]["end_utc"]).normalize() + pd.Timedelta(days=1))
    pending, last = {}, None
    if state_f.exists():
        st = pickle.loads(state_f.read_bytes()); pending, last = st["pending"], st["last"]
        days = days[days > last]
        log(STEP, f"radar {rid}: resuming after {last:%Y-%m-%d}")
    elif out_csv.exists():
        out_csv.unlink()
    with ThreadPoolExecutor(workers) as ex:
        for day, body in zip(days, ex.map(lambda d: fetch(rid, d), days)):
            if body is None:
                log(STEP, f"radar {rid} {day:%Y-%m-%d}: no file (404)")
            else:
                for vt, p in scans(body):
                    h = vt.ceil("1h")
                    for cid, ix in idx.items():
                        v = p[ix]
                        s, b, n = pending.get((cid, h), (np.zeros(ix.size), np.zeros(ix.size, bool), 0))
                        pending[(cid, h)] = (s + np.nan_to_num(v), b | np.isnan(v), n + 1)
            done = [k for k in pending if k[1] <= day]                 # hours ending by 00:00 of this day
            rows = [summarise(k[0], k[1], *pending.pop(k)) for k in sorted(done, key=lambda k: (k[1], k[0]))]
            if rows:
                pd.DataFrame(rows).to_csv(out_csv, mode="a", header=not out_csv.exists(), index=False)
            state_f.write_bytes(pickle.dumps({"pending": pending, "last": day}))
            if day.day == 1:
                log(STEP, f"radar {rid}: {day:%Y-%m} started")
    log(STEP, f"radar {rid}: finished -> {out_csv.name}")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=4); a = ap.parse_args()
    cat = catchments()
    for rid in sorted(cat.radar_id.unique()):
        m = np.load(SHARED / "masks" / f"radar{rid}.npz")
        idx = {cid: np.flatnonzero(m[cid].ravel()) for cid in cat[cat.radar_id == rid].catchment_id}
        run(rid, idx, a.workers)


if __name__ == "__main__":
    main()
