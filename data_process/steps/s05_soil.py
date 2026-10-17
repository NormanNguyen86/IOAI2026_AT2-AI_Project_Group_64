"""Step 5: AWRA-L daily soil water per catchment (NCI THREDDS, NetcdfSubset by bounding box).

Raw:     data/raw/awra/<catchment_id>/<var>_<year>.nc   the subset exactly as served
Interim: data/interim/soil_daily.csv   catchment_id, date, soil_upper_mm, soil_lower_mm
         (mean of the 0.05 deg cells listed in data/interim/awra_cells.json)
"""
import json
import pandas as pd
import xarray as xr
from common import CFG, RAW, INTERIM, download, catchments, log, utc

STEP = "s05"
BASE = "iu04/australian-water-outlook/historical/v1/AWRALv7"


def main():
    cells = json.loads((INTERIM / "awra_cells.json").read_text())
    start, end = utc(CFG["period"]["start_utc"]), utc(CFG["period"]["end_utc"])
    frames = []
    for cid in catchments().catchment_id:
        c = cells[cid]; s, n, w, e = c["bbox"]
        cols = {}
        for var, name in CFG["soil"]["variables"].items():
            parts = []
            for y in range(start.year, end.year + 1):
                f = RAW / "awra" / cid / f"{var}_{y}.nc"
                if not f.exists():
                    download(f"{CFG['urls']['thredds']}/ncss/grid/{BASE}/{var}_{y}.nc",
                             params={"var": var, "north": n, "south": s, "west": w, "east": e,
                                     "time_start": f"{y}-01-01T00:00:00Z", "time_end": f"{y}-12-31T00:00:00Z",
                                     "accept": "netcdf4"}, save_to=f, step=STEP)
                with xr.open_dataset(f) as ds:
                    pts = [ds[var].sel(latitude=la, longitude=lo, method="nearest") for la, lo in c["cells"]]
                    parts.append(xr.concat(pts, "cell").mean("cell").to_series())
            cols[name] = pd.concat(parts)
        d = pd.DataFrame(cols); d.index = pd.to_datetime(d.index).date; d.index.name = "date"
        frames.append(d.reset_index().assign(catchment_id=cid))
        log(STEP, f"{cid}: {len(d)} days")
    out = pd.concat(frames)[["catchment_id", "date"] + list(CFG["soil"]["variables"].values())]
    out.to_csv(INTERIM / "soil_daily.csv", index=False)


if __name__ == "__main__":
    main()
