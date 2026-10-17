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

## 3. How the label is made

The question every model answers is: **"Will the river at this gauge start to flood within the next 6 hours?"** It is answered once per catchment per hour.

### 3.1 Threshold: what "flood" means at a gauge
- The threshold is a **river level in metres at the outlet gauge**, measured from that gauge's own zero. It is not a flood depth, and it cannot be compared between gauges (1.21 m at 204030, 6.01 m at 204906).
- **Default (`p99_train`):** the 99th percentile of the gauge's hourly maximum level over the **train** hours only (holdout excluded). The river is above it about 1% of the time (about 88 h a year).
  - It means "unusually high water for this gauge".
  - Train-only avoids using information from the validation or test years.
- **Better, when available (`manual`):** the official *minor flood level* published by BoM/SES for the gauge, set by impact (low roads and bridges start to flood). Enter it in `config.json → label.manual_thresholds`.
- **Limit:** p99 is statistical. At some gauges it is below the official minor level, so some positives are high flows that do no damage. At others it may be above it.

### 3.2 From river level to flood events (`shared/events.csv`)
1. **Hourly level.** BoM 15-min readings are turned into the **maximum level in each UTC hour (h − 1 h, h]**.
2. **Onset.** The first hour the level is above the threshold after it has been **below for at least 6 h** (`label.onset_min_hours_below`).
3. **End.** The first hour back below the threshold.
4. **Short dips.** If the river rises above again after fewer than 6 h below, the rise is **merged into the previous event**, which then continues. It is neither a new onset nor a "no flood" hour.
   - Of 434 upward crossings in the current data, 390 are onsets and 44 are merged.
   - The old 24 h rule would have missed 97 crossings, including the main Lismore peak of 27 Feb 2022 at 203010.

### 3.3 From events to one label per issue hour (`shared/samples.csv`)
For each catchment and each whole hour `t` (the issue time):

| Situation at issue time t | Result |
|---|---|
| An onset falls in (t, t + 6 h] | `label = 1` |
| No onset in (t, t + 6 h], river below threshold at t | `label = 0` |
| River already above threshold at t (inside an event) | **row removed**: the flood has already started, so there is nothing to forecast |
| River level missing at t or in any hour of (t, t + 6 h] | **row removed**: the label is unknown |
| Any of the 72 radar hours before t unusable (section 4.4) | **row removed**: incomplete input |
| t within 78 h of a change of split (not holdout) | **row removed**: input or label window would cross two sets |

**Example (Leycester River at Rock Valley, 203010, threshold 2.631 m).** The onset is at 12:00 UTC on 26 Feb 2022.
- Issue times 06:00–11:00 → label 1.
- Issue times up to 05:00 → label 0.
- From 12:00 until the river falls back below 2.631 m → removed.

### 3.4 Why "onset" and not "above threshold at any time in the next 6 h"
The second definition gives 4–5 times more positives (train 1.22% instead of 0.29%; holdout 20.8% instead of 2.8%). But almost all the extra positives are hours when the river is **already** flooding. Those are easy to predict ("still flooding in the next hour") and have no warning value, so they would inflate scores and blur the comparison between candidates. The imbalance is instead handled in training (class weights or undersampling negatives in train only, then probability calibration).

## 4. What the data look like (run of 17 Oct 2026)

Charts and longer notes for each part are in `notebooks/inspect_data.ipynb` (same section names); the full tables are in `data/report.md`.

### 4.1 Catchments and radar domains
- 13 catchments pass the rule, out of 65 NSW CAMELS-AUS catchments of 20–500 km².
- **Size:** 63–433 km².
- **Radar:**
  - 10 use Grafton (radar 28, 58–127 km away);
  - 3 use Mt Stapylton (radar 66: 201001, 203010, 204039; 71–147 km away).
  - Radar estimates may be weaker for the farthest catchments, because the beam is higher above the ground there.
- **Extent:** 9–37 km across. Only 204017, 204025 and 204037 fit a 16 km map tile.
- **Static attributes:** they vary widely (mean elevation 157–1,303 m, slope 7–29%, forest 17–100%). Urban share is about 0 everywhere and carries little information.

### 4.2 River level (label source)
- 97–100% of hours have a reading in every year.
- The lower 2026 values (93–99%) are recent data still being processed by BoM.
- Some gauges flat-line during the 2019 drought, and a few show step changes (possible datum or sensor changes). None creates a false onset.

### 4.3 Flood events
- **392 onsets:** train 231, val 18, test 84, holdout 59.
- **Seasonality:** 81% fall in December–May, 46% in February–March, 9% in June–September.
- **Duration:** median 14 h above threshold; 29% last 6 h or less.

### 4.4 Radar rain
Each radar hour is built from four 15-min files. An hour is **usable** only if all of these hold:
- all 4 scans exist;
- at least 90% of the catchment has data;
- no cell carries the fill code (≥ 300 mm/h; the stored value 65535 means 3,276.7 mm);
- the catchment maximum is not stuck at one value for ≥ 6 h while ≥ 20 mm/h;
- the hour is not in a manual exclusion (`radar.qc_exclude`, each entry with a written reason).

| | Grafton (28) | Mt Stapylton (66) |
|---|---|---|
| Days missing on NCI | 33 | 50 |
| Hours with 1–3 of 4 scans | 533 (322 have 3 scans) | 481 (331 have 3 scans) |
| Usable hours | 96.5–97.0% | 96.2% |

- **Plausibility:** annual totals follow known climate (dry 2019 and 2023, wet 2020–2022 and 2025). Coastal catchments are about twice as wet as tableland ones.
- **Suspected artefacts:** three periods with extreme rain but almost no river response. One is excluded (204056, April 2024); two are under review (see section 7).

### 4.5 Soil water (AWRA-L)
- No gaps.
- **Upper layer (0–0.1 m):** reacts within a day.
- **Lower layer (0.1–1 m):** carries the seasonal wetness. It is near empty in 2019 and late 2023, and near full in 2020–2022.
- Values are model estimates (daily, about 5 km). Each hour uses the previous local day.

### 4.6 Master table
- **564,708 rows**, about 70% of all candidate issue hours.
- **Positives:**

  | Split | Positives | Share |
  |---|---|---|
  | train | 1,088 | 0.29% |
  | val | 72 | 0.09% |
  | test | 299 | 0.29% |
  | holdout | 334 | 2.8% |

- **Why rows are dropped:** almost entirely radar gaps (about 28% of candidate hours). Level gaps and "already in flood" remove at most about 1,000 hours per catchment.
- **Test period:** 214 of the 299 test positives fall in January–March 2025.

## 5. Run

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

## 6. What each member uses

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

## 7. Open decisions for the team

The data above are final for now. These choices change the data and need agreement first. Each needs only `config.json` edits and a partial rerun.

### 7.1 Two more suspected radar artefacts
- **204056, ending 2 July 2024:** 562 mm in 72 h, but the river reached only 0.40 m.
- **204037, ending 16 April 2024:** 456 mm in 72 h, but the river reached only 0.37 m.

Rain like this on small, steep catchments cannot leave the river at baseflow. The real floods in the data show the expected response: 203010 had 453 mm and rose to 13.2 m.

- **If kept:** the model learns that extreme rain can produce no flood. This pushes predicted probabilities down in exactly the situations where a warning matters.
- **If excluded:** we lose about 2 weeks of rows at two catchments.
- **To exclude:** add both periods to `radar.qc_exclude` with this evidence as the reason, then run `python run_all.py --only 6 7 8`.

### 7.2 Accept radar hours with 3 of 4 scans?
- **What a missing scan is.** Each radar hour is the sum of four 15-min accumulation files. A missing scan means one of those files is absent at NCI, usually because of a radar outage, maintenance or a data transfer gap. The whole radar is affected, not one catchment. For that hour, 15 minutes of rain are simply unknown.
- **How often.** 322 hours (Grafton) and 331 hours (Mt Stapylton) have exactly 3 scans. A further 211 and 150 hours have only 1–2 scans and stay unusable in any case.
  - Most are isolated single hours: 368 of 413 partial-hour runs at Grafton.
  - About a third sit at the edge of a longer outage.
  - We found no sign that they are more frequent in rainy hours.
- **Why it matters.** One unusable hour removes every issue time whose 72 h history contains it. So these few hundred hours cost about 12 percentage points of usable issue times: the share would rise from 71.9% to 84.4% if they were accepted.
- **Risks if accepted:**
  1. **Under-estimated rain.**
     - Summing 3 scans misses up to a quarter of the hour.
     - Scaling by 4/3 assumes the missing 15 minutes rained like the other 45. That is wrong for a short convective burst, which is exactly the rain that triggers flash floods.
     - Either way, the error is largest in the hours that matter most.
  2. **Inconsistent inputs between candidates.** A, B and C must apply the same fill rule, or they are no longer compared on equal inputs.
  3. **Possible bias at outage edges.** If outages are linked to storms (power or communication failures), the hours next to them may be systematically wrong.
  4. **More code to verify.** The scaling has to be added to `s04_radar.py` and `radar_maps.py`, and steps 4–8 rerun (about 45 minutes).
- **A middle way:**
  - accept a 3-scan hour only if it is the only partial hour in the 72 h window;
  - and add `n15` (scan count) as an extra input, so the model knows the hour is less reliable.

### 7.3 Official minor flood levels
Replacing `p99_train` thresholds with official minor flood levels makes "flood" mean "impact begins" rather than "unusually high water".
- **How:** collect the levels from BoM flood warning pages or local SES flood plans, enter them in `label.manual_thresholds`, and run `python run_all.py --only 3 6 7 8`.
- **Effect:** the numbers of events and positives will change.

### 7.4 The validation year is thin
- Jul 2023 – Jun 2024 has only 18 onsets (72 positive rows), and 4 catchments have none. Choosing an alert threshold or a best epoch on this is unreliable.
- **Options:**
  - time-based cross-validation inside the train years (for example leave-one-water-year-out);
  - or keep the split and report validation scores with bootstrap-by-event uncertainty.

### 7.5 Tile size for member A
- Only 3 of 13 catchments fit a 16 km tile (section 6, Member A).
- This must be agreed before A builds tiles, because it decides how much of each catchment's rain the CNN can see.

## 8. Conventions verified on real data

- Radar files are stamped with the **end** of the 15 minutes (`valid_time`), in UTC.
- BoM hourly-mean level values are stamped at the **start** of the hour. The pipeline therefore uses the 15-min readings and takes the hour-ending maximum itself.
- KiWIS timestamps carry +10:00. They are converted to UTC.
- The radar fill code (65535 → 3,276.7 mm) appears in a few files and is treated as missing.
- The Python radar step reproduces the browser prototype's catchment rain for Dec 2021 – Apr 2022 to within 0.005 mm. `radar_maps.py` tiles agree with the hourly table: the 6 h sum at 203010 was 109.6 mm vs 110.1 mm.

## 9. Folder layout

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
