# data_process: reproducible data collection for the flash flood study

Every number used for training can be traced back to a public source:
- **Before any download**, the study area, catchment rule, period, split, label rule and quality-control rules are fixed in `config.json`.
- **Every request** the scripts make is logged in `data/manifest.csv`: URL, time, HTTP status, size and SHA-256.
- **Two files** must be downloaded by hand. Their exact names and source are given below.

## 1. Set up (once)

```bash
pip install -r requirements.txt          # Python 3.10+
```

**Manual download (no account needed).** Go to https://zenodo.org/records/14289037 (CAMELS-AUS v2, CC BY 4.0). Download the two files below and put them in `data/manual/` with their names unchanged:

| File | Used for |
|---|---|
| `CAMELS_AUS_Attributes&Indices_MasterTable.csv` | Catchment list, outlet coordinates, static attributes |
| `02_location_boundary_area.zip` | Catchment boundaries (shapefile inside) |

Everything else is downloaded automatically from two public services:
- `thredds.nci.org.au`: radar rain (Rainfields3) and soil water (AWRA-L)
- `www.bom.gov.au`: river level (Water Data Online, KiWIS API)

## 2. Decisions fixed in `config.json`

| Item | Value | Why |
|---|---|---|
| Catchments | CAMELS-AUS v2, NSW, 20–500 km², ≥ 99% inside the Grafton (28) or Mt Stapylton (66) radar grid | Published boundaries and attributes; small enough for flash floods |
| Period | 08 Jun 2019 – 30 Jun 2026 (UTC) | Rainfields3 on NCI starts 08 Jun 2019; later data are provisional |
| Split | train 08 Jun 2019 – 30 Jun 2023 · val Jul 2023 – Jun 2024 · test Jul 2024 – Jun 2026 · holdout 20 Feb – 10 Apr 2022 · 78 h gaps at every change | Chronological, so one storm is never in two sets; Lismore floods kept as an extreme test |
| Time | UTC; a value stamped h covers (h − 1 h, h]; 72 h history; 6 h horizon | Same rule for A, B and C |
| Label | Flood onset at the outlet gauge in (issue, issue + 6 h] | — |
| Threshold | Official minor level if entered in `label.manual_thresholds`, otherwise the 99th percentile of hourly level over **train years only** | No look-ahead into val/test |
| Onset | First hour above the threshold after ≥ 6 h below. A rise after fewer hours below is merged into the previous event (excluded, never labelled 0) | Keeps a second flood peak after a short dip |
| Radar QC | An hour is unusable if any scan is missing, coverage < 90%, a cell carries the fill code (≥ 300 mm/h), the catchment maximum is stuck (same value ≥ 6 h, ≥ 20 mm/h), or it lies in a documented manual exclusion (`radar.qc_exclude`) | Missing or wrong rain is never treated as 0 mm |

## 3. Run

```bash
python run_all.py              # steps 1-8
python run_all.py --from 4     # resume (the radar step also resumes by itself)
python run_all.py --only 3 6 7 8   # after changing label or QC settings (seconds, no downloads)
```

| Step | Script | Source | Output |
|---|---|---|---|
| 1 | `s01_catchments.py` | CAMELS-AUS files + one radar day per radar (grid definition) | `shared/catchments.csv`, `shared/boundaries.geojson`, `shared/masks/radar<ID>.npz`, `data/raw/radar_grid/`, `data/interim/awra_cells.json`, `data/processed/b/static.csv` |
| 2 | `s02_levels.py` | BoM KiWIS, series `DMQaQc.Merged.AsStored.1` (15-min readings) | `data/raw/levels/<awrc>/<year>.json` (as served); `data/interim/levels/<id>.csv` (hourly maximum, UTC) |
| 3 | `s03_events.py` | step 2 | thresholds in `shared/catchments.csv`; `shared/events.csv` |
| 4 | `s04_radar.py` | NCI `rq0/rainfields3/<radar>/<year>/prcp-m15/` daily zips | `data/interim/radar/radar<ID>_hourly.csv` |
| 5 | `s05_soil.py` | NCI `iu04/…/AWRALv7/s0_<year>.nc`, `ss_<year>.nc` (bounding-box subsets) | `data/raw/awra/<id>/…nc`; `data/interim/soil_daily.csv` |
| 6 | `s06_samples.py` | steps 2–5 | **`shared/samples.csv`**, the master table for A, B and C |
| 7 | `s07_build_b.py` | steps 1, 4, 5 | `data/processed/b/dynamic_hourly.parquet`, `preview_one_window.csv` (add `--npz val test holdout` for arrays) |
| 8 | `s08_report.py` | all | `data/report.md`: sources, split, catchments, radar quality, level completeness, events, samples, limitations |

**Running time and disk:**
- Steps 1–3 take about 3 minutes; step 5 takes about 2 minutes.
- Step 4 takes about 20–25 minutes per radar for the full period (measured on 17 Oct 2026). It downloads about 8.8 GB in total but keeps none of it.
- Set `radar.keep_raw_zips` to `true` to keep the radar zips (about 0.6 GB per radar-year).

**After a run**, open `notebooks/inspect_data.ipynb`. It inspects every source with charts and written notes, and runs 7 automatic checks. See `data/DATA_DICTIONARY.md` for every file and column.

## 4. What each member uses

All members predict the **same rows** of `shared/samples.csv` (`catchment_id, issue_utc, label, split`) and must use only data at or before `issue_utc`. Never add, drop or re-label rows: a missing prediction counts as a gap in the comparison.

### Member B (sequence model, LSTM)

```python
import sys; sys.path.insert(0, "steps")
from b_dataset import WindowDataset
train = WindowDataset("train")      # x_dyn (72, 6), x_static (13,), y for every train row
```
- **Dynamic features:**
  - `rain_mean`, `rain_max`, `rain_p90`: catchment rain statistics, mm/h;
  - `rain_frac_heavy`: share of cells ≥ 2 mm/h;
  - `soil_upper_mm`, `soil_lower_mm`: previous local day's value.
- **Static features:** 13 CAMELS-AUS attributes (see `config.json`).

### Member A (CNN on map tiles)

Apart from `samples.csv`, these files are ready for A:

| File | What A gets from it |
|---|---|
| `shared/catchments.csv` | Outlet gauge (lat, lon), area, which radar covers it (`radar_id`), flood threshold |
| `shared/boundaries.geojson` | Catchment polygon (WGS84): rasterise it on A's own grid for the **catchment-mask channel** and to centre the tile |
| `steps/radar_maps.py` | **Rain channels 1–3.** `catchment_tile(cid, issue_utc, hours=[1, 3, 6], size_km=16, cell_m=250)` returns rain sums over the last 1/3/6 h on a 64 × 64 EPSG:3577 tile, plus the mask. It uses the same radar files, hour convention and fill-code rule as B. `rain_sum(radar_id, issue_utc, h)` gives the full 512 × 512 radar field. Daily zips are cached in `data/raw/radar_cache/` and logged in the manifest |
| `data/raw/radar_grid/radar<ID>.json` | Radar grid definition (x/y in km, Albers projection string) if A prefers to work on the radar's native 0.5 km grid |
| `shared/masks/radar<ID>.npz` | Catchment masks already on the radar grid (512 × 512, one array per catchment) |
| `data/interim/radar/radar<ID>_hourly.csv` | Hourly quality flags (`n15`, `coverage`) and catchment rain. Use them to check a tile; unusable hours are already excluded from `samples.csv` |
| `data/interim/soil_daily.csv` | AWRA-L soil water per catchment and day for the **soil-wetness channel**. AWRA-L is about 5 km, so a 16 km tile holds only about 3 × 3 cells. A catchment value (previous local day) carries almost the same information as a map. For a map, request the tile's bounding box with the URL pattern in `s05_soil.py` |
| `config.json` | Time convention, split dates, QC rules: use the same values, do not copy numbers by hand |
| `shared/events.csv` | Flood onsets and ends, for event-based evaluation (for example hypothesis H1: localised vs prolonged rain) |
| `data/interim/levels/<id>.csv` | River level, for case-study plots |
| `data/processed/b/static.csv` | CAMELS-AUS catchment attributes. These are not maps, but A can use them for error analysis or as extra scalar inputs |

**Not produced by this pipeline (A downloads them):** the static map layers DEM-S (elevation, slope, flow accumulation), SLGA soil and DEA Land Cover. They do not change in time, so they need only one download per catchment tile.

**Three things A must check before training:**
1. **Tile size.** Only 3 of 13 catchments (204017, 204025, 204037) fit in a 16 km tile. The others extend 18–37 km, so `data/report.md` §4 lists the extents. Options:
   - use a larger tile (for example 40 km at 625 m cells keeps 64 × 64);
   - crop to the catchment's bounding box and resize;
   - keep 16 km and report coverage (`catchment_tile(...)["catchment_share_in_tile"]`).
2. **Resolution.** Radar is 0.5 km. Resampling to 250 m duplicates cells and adds no detail.
3. **Speed.** For about 565,000 samples, build tiles day by day: one zip serves 24 issue hours. Do not re-open the zip for every sample.

### Member C (foundation model)

C reads `shared/samples.csv` and chooses its own inputs. The files listed for A (radar fields via `radar_maps.py`, boundaries, soil, static attributes) are available to C as well.

## 5. Current dataset (run of 17 Oct 2026)

| | |
|---|---|
| Catchments | 13: 10 on Grafton radar, 3 on Mt Stapylton; 63–433 km² |
| Flood onsets | 392 (train 231 · val 18 · test 84 · holdout 59) |
| Samples | 564,708 (positives: train 1,088 · val 72 · test 299 · holdout 334) |
| Radar | 96–97% of hours usable; 83 radar days missing on NCI; 1 manual exclusion (204056, April 2024) |

**Open decisions for the team** (details in the notebook):
1. Two more suspected radar artefacts to review: 204056 July 2024 and 204037 April 2024.
2. Accept hours with 3 of 4 scans? Usable issue times would rise from 71.9% to 84.4%.
3. Enter official minor flood levels where they exist.
4. The validation year is thin (18 events): use time-based cross-validation inside train, or report wide uncertainty.
5. Agree the tile size with member A.

## 6. Conventions verified on real data

- Radar files are stamped with the **end** of the 15 minutes (`valid_time`), in UTC.
- BoM hourly-mean level values are stamped at the **start** of the hour. The pipeline therefore uses the 15-min readings and takes the hour-ending maximum itself.
- KiWIS timestamps carry +10:00. They are converted to UTC.
- The radar fill code (65535 → 3,276.7 mm) appears in a few files and is treated as missing.
- The Python radar step reproduces the browser prototype's catchment rain for Dec 2021 – Apr 2022 to within 0.005 mm. `radar_maps.py` tiles agree with the hourly table: the 6 h sum at 203010 was 109.6 mm vs 110.1 mm.

## 7. Folder layout

```
data_process/
  README.md           this file
  config.json         all decisions (edit here only)
  run_all.py          runs steps 1-8
  requirements.txt
  logs.txt            console output of your runs (optional, kept by you)
  steps/              s01-s08, common.py (config, downloads, QC), b_dataset.py (B), radar_maps.py (A, C)
  notebooks/          inspect_data.ipynb
  shared/             files every candidate uses
  data/manual/        the two hand-downloaded CAMELS-AUS files
  data/raw/           downloads kept as served
  data/interim/       per-source tables (UTC, hourly or daily)
  data/processed/b/   Candidate B's model inputs
  data/manifest.csv   provenance of every download
  data/report.md      summary written by step 8
  data/DATA_DICTIONARY.md   every file and column
```
