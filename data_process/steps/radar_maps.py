"""Gridded rain for map-based models (Candidate A, C). Uses the same files, hour convention and QC
idea as the pipeline, but keeps the 2-D field instead of catchment statistics.

    import sys; sys.path.insert(0, "steps")
    from radar_maps import rain_sum, catchment_tile
    r = rain_sum("28", "2022-02-27T18:00:00Z", hours=6)          # dict: mm (512x512), x_km, y_km, proj4, n_scans
    t = catchment_tile("203030", "2022-02-27T18:00:00Z", hours=[1, 3, 6], size_km=16, cell_m=250)
    t["rain"].shape   # (3, 64, 64) mm over the last 1, 3, 6 h;  t["mask"] (64, 64) 1 = inside catchment

Rules (same as shared/samples.csv):
  - the window for `hours=h` is (issue - h, issue]; scans are stamped with the END of their 15 minutes;
  - a cell is NaN if any of its scans in the window is missing; fill code (>= qc_max_mm_per_hour) is NaN;
  - only data at or before the issue time is read.
Daily zips are cached in data/raw/radar_cache/<radar>/ (about 3-12 MB per day) and logged in data/manifest.csv.
"""
import io, json, zipfile
import numpy as np
import pandas as pd
import netCDF4
from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely import contains_xy
from common import CFG, RAW, SHARED, download, utc, catchments

R = CFG["radar"]


def _day_zip(rid, day):
    f = RAW / "radar_cache" / rid / f"{rid}_{day:%Y%m%d}.{R['product']}.zip"
    if f.exists():
        return f.read_bytes()
    url = f"{CFG['urls']['thredds']}/fileServer/rq0/rainfields3/{rid}/{day:%Y}/{R['product']}/{rid}_{day:%Y%m%d}.{R['product']}.zip"
    return download(url, save_to=f, step="radar_maps")


def grid(rid):
    return json.loads((RAW / "radar_grid" / f"radar{rid}.json").read_text())


def rain_sum(rid, issue_utc, hours=6):
    """Sum of 15-min accumulations with valid time in (issue - hours, issue]. Returns mm on the radar grid."""
    t1 = utc(issue_utc); t0 = t1 - pd.Timedelta(hours=hours)
    need = pd.date_range(t0 + pd.Timedelta(minutes=15), t1, freq="15min")
    total, bad, seen = None, None, set()
    for day in sorted({t.normalize() for t in need}):
        body = _day_zip(rid, day.tz_localize(None))
        if body is None:
            continue
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            for name in z.namelist():
                if not name.endswith(".nc"):
                    continue
                stamp = pd.Timestamp(name.split("_")[1] + name.split("_")[2][:6], tz="UTC")
                if stamp not in need:
                    continue
                with netCDF4.Dataset("mem", memory=z.read(name)) as ds:
                    p = ds["precipitation"][:].filled(np.nan)
                p[p >= R.get("qc_max_mm_per_hour", 1e9)] = np.nan
                total = np.zeros_like(p) if total is None else total
                bad = np.zeros(p.shape, bool) if bad is None else bad
                total += np.nan_to_num(p); bad |= np.isnan(p); seen.add(stamp)
    g = grid(rid)
    out = {"x_km": np.array(g["x_km"]), "y_km": np.array(g["y_km"]), "proj4": g["proj4"], "n_scans": len(seen), "n_expected": len(need)}
    if total is None or len(seen) < len(need):
        out["mm"] = None                       # incomplete window -> treat as missing
    else:
        total[bad] = np.nan; out["mm"] = total
    return out


def catchment_tile(catchment_id, issue_utc, hours=(1, 3, 6), size_km=16, cell_m=250):
    """Rain sums for several windows resampled (nearest cell) to a square tile on EPSG:3577,
    centred on the catchment, plus the catchment mask on the same tile."""
    cat = catchments().set_index("catchment_id")
    rid = cat.radar_id[catchment_id]
    feat = [f for f in json.loads((SHARED / "boundaries.geojson").read_text())["features"]
            if f["properties"]["catchment_id"] == catchment_id][0]
    to_alb = Transformer.from_crs("EPSG:4326", "EPSG:3577", always_xy=True)
    P = shape(feat["geometry"]); c = P.centroid
    cx, cy = to_alb.transform(c.x, c.y)
    n = int(round(size_km * 1000 / cell_m)); off = (np.arange(n) - (n - 1) / 2) * cell_m
    X, Y = np.meshgrid(cx + off, cy - off)                      # row 0 = north
    lon, lat = Transformer.from_crs("EPSG:3577", "EPSG:4326", always_xy=True).transform(X, Y)
    g = grid(rid)
    rx, ry = Transformer.from_crs("EPSG:4326", CRS.from_proj4(g["proj4"]), always_xy=True).transform(lon, lat)
    xk, yk = np.array(g["x_km"]), np.array(g["y_km"])
    ix = np.clip(np.round((rx - xk[0]) / (xk[1] - xk[0])).astype(int), 0, len(xk) - 1)
    iy = np.clip(np.round((ry - yk[0]) / (yk[1] - yk[0])).astype(int), 0, len(yk) - 1)
    rain = []
    for h in hours:
        r = rain_sum(rid, issue_utc, h)["mm"]
        rain.append(np.full((n, n), np.nan) if r is None else r[iy, ix])
    mask = contains_xy(P, lon, lat).astype(np.uint8)
    return {"rain": np.stack(rain), "hours": list(hours), "mask": mask, "centre_epsg3577": (cx, cy),
            "cell_m": cell_m, "radar_id": rid, "catchment_share_in_tile": float(mask.sum() * cell_m**2 / 1e6 / cat.area_km2[catchment_id])}
