# Shared data: flash flood probability for the next 6 hours

This folder is the one place where the team agrees on **where**, **when** and **what counts as a flood**.
Each model builds its own inputs, but every model scores the same rows of `samples.csv`.

## 1. Scenario

The study area is the **Richmond River basin (Northern Rivers, NSW)**.
- **Catchments:** the outlet of each one is a river gauge on a creek or upper river. `catchments.csv` lists 16 BoM gauges as a starting shortlist.
- **Question:** at each whole hour, will the river at the gauge rise above its flood level within the next 6 hours?
- **Held-out test:** the Lismore floods of Feb to Apr 2022 are kept out of training. Several of the gauges (Leycester, Terania, Goolmangar and Coopers creeks, and the upper Wilsons River) drain towards Lismore.
- **Inputs:** each model uses up to 72 hours of history before the issue time. A uses the last 6 hours as maps; B uses all 72 hours as a time series.

## 2. Files

| File | Format | Written by | Read by | Content |
|---|---|---|---|---|
| `config.json` | JSON | team (once) | all scripts and models | Grid, time convention, period, split, label and missing-data rules |
| `catchments.csv` | CSV | step 2 | all | One row per outlet gauge |
| `masks/{catchment_id}.tif` | GeoTIFF, EPSG:3577, 250 m | step 3 (A) | A and B | 1 inside the catchment, 0 outside |
| `events.csv` | CSV | `scripts/detect_events.py` | `build_samples.py` | Flood onset and end per gauge |
| `missing_hours.csv` | CSV (optional) | step 5 | `build_samples.py` | Hours with too little radar data |
| `samples.csv` | CSV | `scripts/build_samples.py` | **all models** | The master table: what to predict |

**Why these formats:**
- CSV for small tables, because it opens in Excel, pandas or R and is easy to read in a diff.
- JSON for settings, because it is easy to read in code.
- GeoTIFF for maps, because it keeps the coordinates.

Large model-specific data (B's hourly series, A's tiles) are not shared. They belong in each person's own folder, as Parquet, NetCDF or NPY.

## 3. Fields

Only fields that cannot be computed from others are stored.

**catchments.csv**

| Field | Meaning |
|---|---|
| `catchment_id` | BoM station number of the outlet gauge |
| `awrc_id` | State station number. Use it to download the level series from Water Data Online; blank if none |
| `name` | Gauge name |
| `lat`, `lon` | Gauge position (GDA94, EPSG:4283) |
| `threshold_m` | Flood level in metres. **To fill** |
| `threshold_type` | `minor` (official BoM flood class) or `p99` (fallback in `config.json`). **To fill** |

These are not stored because they come from the mask: area, extent, whether the catchment fits A's 16 km tile, and tile centre.

**events.csv**

| Field | Meaning |
|---|---|
| `catchment_id` | Gauge |
| `onset_utc` | First hour above the threshold after at least 24 h below it |
| `end_utc` | First hour back below the threshold |

**samples.csv** (master table)

| Field | Meaning |
|---|---|
| `catchment_id` | Gauge |
| `issue_utc` | Time the forecast is made (whole hour, UTC) |
| `label` | 1 if a flood onset falls in (issue, issue + 6 h], else 0 |
| `split` | `train`, `val`, `test` or `holdout` |

These are not stored because they follow from `issue_utc` and `config.json`: the history window start (issue − 72 h), the label window end (issue + 6 h), and the step times.

Rows that must not be scored are simply absent from `samples.csv`.

## 4. Rules

1. **Time.** Everything is in UTC. A value stamped `h` covers the hour (h − 1 h, h]. The history of a sample is the 72 hours stamped issue − 71 h … issue. The hour stamped issue + 1 h is the future and is never used.
2. **Rain per hour.** Sum the radar scans inside the hour: depth (mm) = rate (mm/h) × scan interval (h). If less than 90% of the expected scans exist, the hour is *missing*, not 0 mm.
3. **Label.** The onset is detected at the outlet gauge with `detect_events.py`. Sentinel-1 images are not used for labels, because they show where water was, not when it arrived.
4. **Not scored.** These issue times are left out of `samples.csv`:
   - times while the gauge is already above the threshold;
   - times whose 72 h history contains a missing hour;
   - times within 78 h of a change of split.
5. **Split.** Feb 20 to Apr 10, 2022 is `holdout`; 2021 is `val`; 2024 is `test`; all other years are `train` (see `config.json`).
6. **Soil moisture.** Every hour of a sample uses the AWRA-L value of the day before the issue date.
7. **Scaling and class balance.** These are each model's own choice, but use training rows only.

## 5. Steps

| # | Week | Owner | Do | Done when |
|---|---|---|---|---|
| 1 | 1 | All | Agree the `TO_CONFIRM` values in `config.json` | Values agreed in the group chat |
| 2 | 1 | B | Open the Rainfields3 catalogue on NCI THREDDS (`rq0/rainfields3`) in a browser and note the first year; set `period.start_utc` to that year or later | Period fixed |
| 3 | 1–2 | A | Download DEM-S for the basin, trace each gauge upstream on the 250 m grid and save `masks/{catchment_id}.tif`; drop gauges whose catchment is wider than 16 km | Masks saved; `catchments.csv` trimmed |
| 4 | 1–2 | B | Fill `threshold_m` (BoM flood class where one exists, else the fallback). For each gauge, download level data from Water Data Online and run `python scripts/detect_events.py --catchment-id <id> --level <file>` | `events.csv` filled |
| 5 | 2 | A + B | Download Rainfields3 for the period, make the hourly rain grid on the shared grid (rule 2), and write the missing hours per catchment to `missing_hours.csv` | Hourly grids exist |
| 6 | 2 | B | Run `python scripts/build_samples.py` | `samples.csv` written; counts per split printed |
| 7 | 2–3 | each | Build your own inputs for every row of `samples.csv` | One input per row |

When you run step 4, check one known flood peak against the BoM graph to confirm the time zone. The script assumes local standard time (UTC+10); change `--utc-offset` if the file differs.

## 6. How a model reads one sample

```python
import json, pandas as pd
cfg = json.load(open("config.json"))
s = pd.read_csv("samples.csv", dtype={"catchment_id": str}, parse_dates=["issue_utc"])
row = s.iloc[0]
hours = pd.date_range(end=row.issue_utc, periods=cfg["time"]["history_hours"], freq="1h")  # 72 stamps

# A: last 1, 3, 6 hours of the hourly rain GRID, cut to the tile around masks/<id>.tif
# B: catchment-mean rain for all 72 stamps from B's own hourly table
#    (key = catchment_id + hour stamp), plus soil and static attributes
```

Both models read the same `hours`. That is the only link they need.

## 7. Sources

All of these were checked on 17 Oct 2026. "No request" means the provider lists no application or approval for this route.

| Data | Where | Licence | No request? |
|---|---|---|---|
| Gauge list and positions | BoM National Flood Gauge Network map service (layer 5) | BoM | Yes |
| River level | Water Data Online (BoM). Also scriptable with R `bomWater` or Python `kiwis-pie` | CC BY 3.0 AU | Yes |
| Flood class levels | BoM flood warning pages / SES local flood plans (copied by hand) | BoM | Yes |
| Radar rain | Rainfields3, NCI THREDDS `rq0/rainfields3`, netCDF4, about 48 h behind real time | CC BY-NC 4.0 | None listed; **years not confirmed** |
| Soil moisture | AWRA-L via Australian Water Outlook (last 10 years); older data on request | BoM | Yes for 10 years |
| Elevation | DEM-S 1 s, data.gov.au (27 GB national download; slope also provided) | CC BY 4.0 | Yes |
| Soil texture | SLGA 90 m, CSIRO Data Access Portal (no saturated conductivity layer) | CC BY | Yes |
| Land cover | DEA Land Cover 30 m, public S3 / STAC (class "Artificial Surface") | CC BY 4.0 | Yes |
| Catchment boundaries (check) | CAMELS-AUS v2, Zenodo (daily flow only, not for labels); Geofabric | CC BY 4.0 | Yes |

Avoid the WaterNSW API: it requires an account.

## 8. Open items

- [ ] First year of Rainfields3 on NCI, and whether downloads need an NCI account
- [ ] Which gauges have official minor flood levels
- [ ] Time zone of Water Data Online exports
- [ ] AWRA-L layer, units and day boundary (9 am local?)
- [ ] Which catchments fit the 16 km tile (after step 3)
