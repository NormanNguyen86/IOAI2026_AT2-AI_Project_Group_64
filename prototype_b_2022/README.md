# Prototype: B's LSTM dataset, Dec 2021 – Apr 2022 (real data)

This is a first working dataset built from real public data. It covers 6 catchments over the 2022 Northern Rivers floods. Its purpose is to prove the whole chain works (sources → shared master table → B's arrays) before scaling up to 2019–2025.

## What is inside

| Path | What |
|---|---|
| `shared_data/` | Shared files in the agreed format. `catchments.csv` (6 gauges, p99 thresholds), `events.csv` (28 flood onsets), `missing_hours.csv` (388 radar hours), `samples.csv` (13,440 rows) and the prototype `config.json` |
| `candidate_b/b_dataset.npz` | **LSTM input.** `X_dyn` (13,440 × 72 × 6), `X_static` (13,440 × 13), `y`, `split`, `catchment_id`, `issue_utc`, feature names |
| `candidate_b/b_dataset_preview.csv` | The 72 input rows of one positive sample, for checking by eye |
| `candidate_b/b_hourly_rain.csv` | Catchment rain per UTC hour (mean, max, p90, share ≥ 2 mm, coverage) |
| `candidate_b/b_soil_daily.csv` | AWRA-L upper (0–10 cm) and lower (10–100 cm) soil water, catchment mean, mm |
| `candidate_b/b_static.csv` | CAMELS-AUS attributes used as the static vector |
| `candidate_b/build_b_dataset.py` | Builds the `.npz` from the files above |
| `candidate_b/fetch_b_inputs.py` | Downloads the same inputs for any period (run where the internet is open) |
| `raw/` | Hourly river levels, catchment boundaries (GeoJSON), radar masks |

**Dynamic features (per hour):** `rain_mean`, `rain_max`, `rain_p90`, `rain_frac_ge2`, `soil_upper_mm`, `soil_lower_mm`. Soil uses the previous local day's value, repeated for all 72 hours.

**Static features:** `catchment_area`, `elev_mean`, `relief`, `mean_slope_pct`, `ksat`, `claya`, `sanda`, `solpawhc`, `lc35_urbanar`, `prop_forested`, `strdensity`, `elongratio`, `p_mean`.

## Catchments

The prototype uses CAMELS-AUS catchments because they come with published boundaries and attributes. All six are inside the Grafton radar (id 28) domain.

| id | Gauge | Area km² | Threshold (p99, m) |
|---|---|---|---|
| 203010 | Leycester River at Rock Valley | 176 | 2.869 |
| 203030 | Myrtle Creek at Rappville | 387 | 3.907 |
| 204017 | Bielsdown Creek at Dorrigo | 74 | 1.925 |
| 204025 | Orara River at Karangi | 134 | 2.124 |
| 204037 | Clouds Creek at Clouds Ck | 63 | 1.608 |
| 204056 | Dandahra Creek at Gibraltar Range | 112 | 1.376 |

Oxley River at Eungella (201001) is outside the Grafton radar domain and needs the Mt Stapylton radar (66).

## Sources actually used

| Data | Route | Notes |
|---|---|---|
| Radar rain | NCI THREDDS `rq0/rainfields3/28/<year>/prcp-m15/` daily zips | Merged gauge/radar 15-min accumulation, 0.5 km Albers grid. Files are stamped with the **end** of the 15 minutes (UTC). Available 2019–2026. Two days missing (2 Feb, 18 Apr 2022) |
| River level | BoM Water Data Online KiWIS, series `DMQaQc.Merged.HourlyMean.HR` | Timestamps carry +10:00; converted to UTC |
| Soil water | NCI THREDDS `iu04/australian-water-outlook/historical/v1/AWRALv7/s0_YYYY.nc`, `ss_YYYY.nc`, NetcdfSubset by bounding box | Daily, 0.05°, mm |
| Boundaries, static | CAMELS-AUS v2 (Zenodo) | Boundary areas match published areas within 0.3 km² |
| Thresholds | 99th percentile of each gauge's hourly level, 2019–2025 | Fallback rule: no official minor flood levels were collected |

## Checks done

- Rain peak at Rock Valley was 22:00 UTC, 27 Feb 2022; the river peak followed 8 hours later (13.2 m at 06:00 UTC, 28 Feb).
- Labels: the onset at 12:00 UTC, 26 Feb gives label 1 to issue times 06:00–11:00. Times from 12:00 are dropped (already in flood).
- The last input hour of every sample equals its issue time, so no future rain is used.
- There are no gaps in `X_dyn`. Every sample with a missing radar hour in its 72 h window was removed earlier, in `samples.csv`.
- `fetch_b_inputs.py` was tested offline on a real Rainfields3 file. It gives the same hour assignment as the browser run.

## Known limits of this prototype

- Only 4 months and 6 catchments. The split is a placeholder: almost all positives (120 of 138) fall in the Lismore holdout window.
- p99 thresholds mark "high flow", not official flood classes.
- KiWIS hourly-mean stamps are taken as hour-ending. Confirm this with BoM before the final run.
- 203010 and 203030 are wider than 16 km, so they do not fit Candidate A's tile.
