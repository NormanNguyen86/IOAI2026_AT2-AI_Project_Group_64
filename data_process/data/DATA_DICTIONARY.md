# Data dictionary

Every file the pipeline writes, what is in it, and which step writes it.
- **Times** are UTC. A value stamped `h` covers the hour (h − 1 h, h].
- **IDs:** `catchment_id` is the outlet gauge's state station number. It is the same number as the CAMELS-AUS `station_id` and BoM's `awrc_id`.

## shared/ (used by every candidate)

| File | Written by | Columns / content |
|---|---|---|
| `samples.csv` | step 6 | `catchment_id`; `issue_utc` (forecast time, whole hour); `label` (1 = flood onset in (issue, issue + 6 h]); `split` (train / val / test / holdout). **Only scoreable rows are present.** |
| `catchments.csv` | steps 1, 2, 3 | `catchment_id`, `awrc_id` (BoM station number), `name`, `lat`, `lon` (outlet, WGS84), `area_km2` (from the polygon), `radar_id` (28 Grafton / 66 Mt Stapylton), `radar_dist_km` (radar to catchment centroid), `mask_cells` (0.5 km radar cells inside), `threshold_m` (flood threshold), `threshold_type` (`p99_train` or `manual`) |
| `events.csv` | step 3 | `catchment_id`, `onset_utc` (first hour above threshold), `end_utc` (first hour back below) |
| `boundaries.geojson` | step 1 | Catchment polygons (WGS84) from CAMELS-AUS v2; property `catchment_id` |
| `masks/radar<ID>.npz` | step 1 | One boolean 512 × 512 array per catchment on that radar's grid (row 0 = north), key = `catchment_id` |

## data/raw/ (as downloaded)

| Path | Content |
|---|---|
| `levels/<awrc_id>/<year>.json` | BoM KiWIS response, 15-min river level (m), timestamps with +10:00 |
| `awra/<catchment_id>/<var>_<year>.nc` | AWRA-L v7 daily subsets (NetCDF4) for the catchment's bounding box: `s0` = 0–0.1 m, `ss` = 0.1–1 m soil water (mm) |
| `radar_grid/radar<ID>.json` | `x_km`, `y_km` (cell centres, 0.5 km), `proj4` (radar-centred Albers), `source_file` (the zip it was read from) |
| `radar_cache/<ID>/…zip` | Only if `radar_maps.py` is used: cached Rainfields3 daily zips |

Radar zips used by step 4 are not kept (set `radar.keep_raw_zips` to keep them); each one is still listed in `manifest.csv` with its SHA-256.

## data/interim/ (per-source tables)

| File | Columns |
|---|---|
| `levels/<catchment_id>.csv` | `hour_end_utc`, `level_max_m` (maximum 15-min reading in the hour) |
| `radar/radar<ID>_hourly.csv` | `catchment_id`, `hour_end_utc`, `n15` (15-min scans found, 4 = complete), `coverage` (share of catchment cells with data), `rain_mean`, `rain_max`, `rain_p90` (mm in the hour over the catchment cells), `rain_frac_heavy` (share of cells ≥ 2 mm/h). QC is applied when the table is read (`common.radar_good`), not written into it. |
| `radar/radar<ID>_state.pkl` | Resume point for step 4 (delete it to re-download from the start) |
| `soil_daily.csv` | `catchment_id`, `date` (AWRA-L day), `soil_upper_mm`, `soil_lower_mm` (mean of the 0.05° cells in the catchment) |
| `awra_cells.json` | Per catchment: `bbox` [south, north, west, east] and the AWRA-L cell centres used for the mean |
| `samples_filter_stats.csv` | `catchment_id`, `candidate` (issue hours in the period), `radar_gap`, `level_gap`, `in_flood` (hours removed for each reason; an hour can fail several), `kept` |

## data/processed/b/ (Candidate B)

| File | Content |
|---|---|
| `dynamic_hourly.parquet` | `catchment_id`, `hour_end_utc` and the 6 dynamic features for every hour. Rain is NaN where radar QC fails; soil = previous local day's AWRA-L value |
| `static.csv` | `catchment_id` and 13 CAMELS-AUS attributes: `catchment_area` (km²), `elev_mean` (m), `relief` (ratio), `mean_slope_pct` (%), `ksat` (saturated conductivity, mm/h), `claya`, `sanda` (% clay, sand in A horizon), `solpawhc` (plant-available water holding capacity, mm), `lc35_urbanar` (urban fraction), `prop_forested` (fraction), `strdensity` (stream density, km/km²), `elongratio` (shape), `p_mean` (mean daily rainfall, mm/day). Definitions: CAMELS-AUS v2 data description |
| `preview_one_window.csv` | The 72 rows of one positive sample, for checking by eye |
| `windows_<split>.npz` | Only with `s07_build_b.py --npz …`: `X_dyn` (N, 72, 6), `X_static` (N, 13), `y`, `catchment_id`, `issue_utc` |

## data/ (top level)

| File | Content |
|---|---|
| `manifest.csv` | `retrieved_utc`, `step`, `status` (HTTP), `url`, `bytes`, `sha256`, `saved_to` |
| `report.md` | Summary written by step 8 |
| `manual/` | The two CAMELS-AUS files downloaded by hand |
