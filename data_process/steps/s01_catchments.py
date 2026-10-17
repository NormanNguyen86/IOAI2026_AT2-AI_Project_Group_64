"""Step 1: choose catchments by the rule in config.json and prepare their geometry.

Needs (manual): CAMELS-AUS v2 attribute table and 02_location_boundary_area.zip in data/manual/.
Downloads: one Rainfields3 day per radar, only to read that radar's grid definition.
Writes: shared/catchments.csv, shared/boundaries.geojson, shared/masks/radar<ID>.npz,
        data/interim/awra_cells.json, data/processed/b/static.csv
"""
import io, json, zipfile, tempfile
import numpy as np
import pandas as pd
import shapefile                                   # pyshp
import xarray as xr
from pyproj import CRS, Transformer, Geod
from shapely.geometry import shape, mapping, box, Point
from shapely.ops import transform as shp_transform
from shapely import contains_xy

from common import CFG, ROOT, RAW, INTERIM, PROCESSED, SHARED, download, log

STEP = "s01"


def radar_grid(rid):
    """Read x/y/projection from the first available day of the radar archive."""
    cache = RAW / "radar_grid" / f"radar{rid}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    day = pd.Timestamp(CFG["period"]["start_utc"]).tz_localize(None) + pd.Timedelta(days=3)
    for k in range(30):
        d = day + pd.Timedelta(days=k)
        url = f"{CFG['urls']['thredds']}/fileServer/rq0/rainfields3/{rid}/{d:%Y}/{CFG['radar']['product']}/{rid}_{d:%Y%m%d}.{CFG['radar']['product']}.zip"
        body = download(url, step=STEP)
        if body:
            break
    with zipfile.ZipFile(io.BytesIO(body)) as z, tempfile.TemporaryDirectory() as td:
        name = sorted(n for n in z.namelist() if n.endswith(".nc"))[0]
        with xr.open_dataset(z.extract(name, td)) as ds:
            p = ds["proj"].attrs
            g = {"x_km": ds.x.values.tolist(), "y_km": ds.y.values.tolist(),
                 "proj4": (f"+proj=aea +lat_1={p['standard_parallel'][0]} +lat_2={p['standard_parallel'][1]} "
                           f"+lat_0={p['latitude_of_projection_origin']} +lon_0={p['longitude_of_central_meridian']} "
                           f"+x_0=0 +y_0=0 +a={p['semi_major_axis']} +b={p['semi_minor_axis']} +units=km +no_defs"),
                 "source_file": url}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(g))
    return g


def read_boundaries(zip_path, ids):
    with zipfile.ZipFile(zip_path) as z:
        base = [n for n in z.namelist() if n.endswith("CAMELS_AUS_v2_Boundaries_adopted.shp")][0][:-4]
        r = shapefile.Reader(shp=io.BytesIO(z.read(base + ".shp")), dbf=io.BytesIO(z.read(base + ".dbf")),
                             shx=io.BytesIO(z.read(base + ".shx")))
        key = r.fields[1][0]
        out = {}
        for sr in r.iterShapeRecords():
            cid = str(sr.record[key])
            if cid in ids:
                out[cid] = shape(sr.shape.__geo_interface__)
    return out


def main():
    rule, mf = CFG["catchment_rule"], CFG["manual_files"]
    att = pd.read_csv(ROOT / mf["camels_attributes"], dtype={"station_id": str})
    sel = att[(att.state_outlet == rule["state"]) &
              att.catchment_area.between(rule["area_km2_min"], rule["area_km2_max"])]
    if rule["include_ids"]:
        sel = pd.concat([sel, att[att.station_id.isin(rule["include_ids"])]]).drop_duplicates("station_id")
    sel = sel[~sel.station_id.isin(rule["exclude_ids"])]
    log(STEP, f"{len(sel)} CAMELS-AUS catchments pass state/area rule")

    polys = read_boundaries(ROOT / mf["camels_boundaries_zip"], set(sel.station_id))
    grids = {rid: radar_grid(rid) for rid in CFG["study_area"]["radars"]}
    geod = Geod(ellps="WGS84")

    rows, feats, masks = [], [], {rid: {} for rid in grids}
    for _, a in sel.iterrows():
        cid = a.station_id
        if cid not in polys:
            continue
        P = polys[cid]
        best = None
        for rid, g in grids.items():
            to_r = Transformer.from_crs("EPSG:4326", CRS.from_proj4(g["proj4"]), always_xy=True).transform
            Pr = shp_transform(to_r, P)
            x, y = np.array(g["x_km"]), np.array(g["y_km"])
            frac = Pr.intersection(box(x.min() - .25, y.min() - .25, x.max() + .25, y.max() + .25)).area / Pr.area
            dist = Pr.centroid.distance(Point(0, 0))
            if frac >= rule["min_mask_inside_radar"] and (best is None or dist < best[2]):
                X, Y = np.meshgrid(x, y)
                m = contains_xy(Pr, X, Y)
                best = (rid, m, dist)
        if best is None:
            continue
        rid, m, dist = best
        masks[rid][cid] = m
        area = abs(geod.geometry_area_perimeter(P)[0]) / 1e6
        rows.append(dict(catchment_id=cid, awrc_id=cid, name=a.station_name.split(" (")[0],
                         lat=a.lat_outlet, lon=a.long_outlet, area_km2=round(area, 1),
                         radar_id=rid, radar_dist_km=round(dist, 1), mask_cells=int(m.sum()),
                         threshold_m="", threshold_type=""))
        feats.append({"type": "Feature", "properties": {"catchment_id": cid}, "geometry": mapping(P)})

    cat = pd.DataFrame(rows).sort_values("catchment_id")
    cat.to_csv(SHARED / "catchments.csv", index=False)
    (SHARED / "boundaries.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    (SHARED / "masks").mkdir(exist_ok=True)
    for rid, d in masks.items():
        if d:
            np.savez_compressed(SHARED / "masks" / f"radar{rid}.npz", **d)

    # AWRA-L 0.05 deg cells whose centre lies in the catchment (nearest cell if none)
    cells = {}
    for cid in cat.catchment_id:
        P = polys[cid]; x0, y0, x1, y1 = P.bounds
        lats = np.round(np.arange(np.floor(y0 / .05) * .05, y1 + .05, .05), 2)
        lons = np.round(np.arange(np.floor(x0 / .05) * .05, x1 + .05, .05), 2)
        c = [[float(la), float(lo)] for la in lats for lo in lons if P.contains(Point(lo, la))]
        if not c:
            cc = P.centroid; c = [[round(round(cc.y / .05) * .05, 2), round(round(cc.x / .05) * .05, 2)]]
        cells[cid] = {"bbox": [round(y0 - .05, 2), round(y1 + .05, 2), round(x0 - .05, 2), round(x1 + .05, 2)], "cells": c}
    (INTERIM / "awra_cells.json").write_text(json.dumps(cells))

    st = att.set_index("station_id").loc[cat.catchment_id, CFG["b_features"]["static"]]
    st.index.name = "catchment_id"
    (PROCESSED / "b").mkdir(exist_ok=True)
    st.to_csv(PROCESSED / "b" / "static.csv")
    log(STEP, f"{len(cat)} catchments kept: " + ", ".join(f"{r.catchment_id}(r{r.radar_id})" for r in cat.itertuples()))


if __name__ == "__main__":
    main()
