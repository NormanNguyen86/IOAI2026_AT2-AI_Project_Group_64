"""Shared helpers: config, paths, and downloads that are logged to data/manifest.csv."""
import csv, hashlib, json, time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config.json").read_text())
DATA = ROOT / "data"
RAW, INTERIM, PROCESSED, SHARED = DATA / "raw", DATA / "interim", DATA / "processed", ROOT / "shared"
MANIFEST = DATA / "manifest.csv"
for d in (RAW, INTERIM, PROCESSED, SHARED):
    d.mkdir(parents=True, exist_ok=True)

_session = requests.Session()
_session.headers["User-Agent"] = "UTS-42172-AT2-flashflood-study (research, non-commercial)"


def utc(x):
    return pd.Timestamp(x).tz_convert("UTC") if pd.Timestamp(x).tzinfo else pd.Timestamp(x, tz="UTC")


def log(step, msg):
    print(f"[{step}] {msg}", flush=True)


def download(url, params=None, save_to=None, step="", retries=4, timeout=300):
    """GET a URL, optionally save it, and append one provenance row to data/manifest.csv.
    Returns the response bytes, or None for HTTP 404 (also logged)."""
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, timeout=timeout)
            break
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    full_url = r.url
    body = r.content if r.status_code == 200 else b""
    row = {
        "retrieved_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "step": step, "status": r.status_code, "url": full_url,
        "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest() if body else "",
        "saved_to": str(save_to.relative_to(ROOT)) if save_to and body else "",
    }
    new = not MANIFEST.exists()
    with MANIFEST.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    if save_to:
        save_to.parent.mkdir(parents=True, exist_ok=True)
        save_to.write_bytes(body)
    return body


def catchments():
    return pd.read_csv(SHARED / "catchments.csv", dtype={"catchment_id": str, "radar_id": str})


def split_of(t, sp=None):
    """Assign train/val/test/holdout to a DatetimeIndex (UTC)."""
    import numpy as np
    sp = sp or CFG["split"]
    out = np.full(len(t), "", dtype=object)
    for name in ("train", "val", "test"):
        a, b = utc(sp[name][0]), utc(sp[name][1])
        out[(t >= a) & (t <= b)] = name
    a, b = utc(sp["holdout"][0]), utc(sp["holdout"][1])
    out[(t >= a) & (t <= b)] = "holdout"
    return out


def radar_good(df):
    """QC for one catchment's hourly radar table sorted by time. True = usable hour."""
    R = CFG["radar"]
    ok = (df.n15 >= R["min_scans_per_hour"]) & (df.coverage >= R["min_coverage"])
    ok &= ~(df.rain_max >= R.get("qc_max_mm_per_hour", 1e9))
    mx = df.rain_max
    run_id = (mx != mx.shift()).cumsum()
    run_len = mx.groupby(run_id).transform("size")
    stuck = (run_len >= R.get("qc_stuck_hours", 10**6)) & (mx >= R.get("qc_stuck_min_mm", 1e9))
    bad = ok & False
    if "catchment_id" in df and len(df):
        t = pd.to_datetime(df.index if isinstance(df.index, pd.DatetimeIndex) else df.hour_end_utc, utc=True)
        for x in R.get("qc_exclude", []):
            bad |= (df.catchment_id == x["catchment_id"]).to_numpy() & (t >= utc(x["start_utc"])) & (t <= utc(x["end_utc"]))
    return ok & ~stuck & ~bad
