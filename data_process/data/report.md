# Data report

Generated 2026-10-17 12:13 UTC by `steps/s08_report.py` from the files in this folder. Regenerate with `python run_all.py --only 8`.
For charts and a discussion of every table, open `notebooks/inspect_data.ipynb`.

## 1. Summary

- Study area: Northern NSW (Richmond, Clarence, Tweed and nearby basins); radars: 28 (Grafton), 66 (Brisbane (Mt Stapylton)).
- Period: 2019-06-08T00:00:00Z to 2026-06-30T23:00:00Z (UTC), 61,920 hours.
- 13 catchments, 392 flood onsets, 564,708 scored samples (1,793 positive).
- Target: flood onset at the outlet gauge in (issue, issue + 6 h]; inputs use up to 72 h before the issue time.

## 2. Sources (from data/manifest.csv)

| step   | host               |   requests |   ok |   not_found |    GB | first                | last                 |
|:-------|:-------------------|-----------:|-----:|------------:|------:|:---------------------|:---------------------|
| s01    | thredds.nci.org.au |          2 |    2 |           0 | 0.002 | 2026-10-17T09:52:28Z | 2026-10-17T09:52:30Z |
| s02    | www.bom.gov.au     |        117 |  117 |           0 | 0.16  | 2026-10-17T09:52:31Z | 2026-10-17T09:55:32Z |
| s04    | thredds.nci.org.au |       5162 | 5079 |          83 | 8.847 | 2026-10-17T09:55:40Z | 2026-10-17T10:32:17Z |
| s05    | thredds.nci.org.au |        208 |  208 |           0 | 0.031 | 2026-10-17T10:40:37Z | 2026-10-17T10:42:18Z |

5,489 requests are logged with URL, time, size and SHA-256. HTTP 404 = the file does not exist at the provider (radar days missing on NCI).

## 3. Split

| set     | from                 | to                   |
|:--------|:---------------------|:---------------------|
| train   | 2019-06-08T00:00:00Z | 2023-06-30T23:00:00Z |
| val     | 2023-07-01T00:00:00Z | 2024-06-30T23:00:00Z |
| test    | 2024-07-01T00:00:00Z | 2026-06-30T23:00:00Z |
| holdout | 2022-02-20T00:00:00Z | 2022-04-10T23:00:00Z |

Issue times within 78 h of a split change are dropped (except holdout), so no input or label window crosses sets.

## 4. Catchments

|   catchment_id | name                                         |   area_km2 |   radar_id |   radar_dist_km |   threshold_m | threshold_type   | extent_km (w x h)   | fits_16km_tile   |
|---------------:|:---------------------------------------------|-----------:|-----------:|----------------:|--------------:|:-----------------|:--------------------|:-----------------|
|         201001 | Oxley River at Eungella                      |      215   |         66 |            71.1 |         1.848 | p99_train        | 18.5 x 21.6         | False            |
|         203010 | Leycester River at Rock Valley               |      176.1 |         66 |            98.9 |         2.631 | p99_train        | 14.1 x 29.4         | False            |
|         203030 | Myrtle Creek at Rappville                    |      387.6 |         28 |            59.6 |         3.119 | p99_train        | 30.3 x 26.1         | False            |
|         204017 | Bielsdown Creek at Dorrigo No.2 & No.3       |       74.1 |         28 |            84.7 |         1.711 | p99_train        | 15.3 x 10.2         | True             |
|         204025 | Orara River at Karangi                       |      134.4 |         28 |            74.1 |         2.013 | p99_train        | 13.1 x 14.9         | True             |
|         204030 | Aberfoyle River at Aberfoyle                 |      208.7 |         28 |           125.6 |         1.212 | p99_train        | 27.3 x 28.3         | False            |
|         204034 | Henry River at Newton Boyd                   |      400.3 |         28 |            91.4 |         1.441 | p99_train        | 37.4 x 21.5         | False            |
|         204036 | Cataract Creek at Sandy Hill(below Snake Cre |      238.7 |         28 |           104.4 |         2.184 | p99_train        | 18.8 x 30.0         | False            |
|         204037 | Clouds Creek at Clouds Ck                    |       62.9 |         28 |            65.6 |         1.48  | p99_train        | 11.6 x 8.7          | True             |
|         204039 | Maryland River at D/S Wylie Ck               |      385.7 |         66 |           147.3 |         1.747 | p99_train        | 27.0 x 29.6         | False            |
|         204056 | Dandahra Creek at Gibraltar Range            |      112.5 |         28 |            58.5 |         1.269 | p99_train        | 17.3 x 10.5         | False            |
|         204906 | Orara River at Glenreagh                     |      432.5 |         28 |            65.9 |         6.013 | p99_train        | 24.4 x 31.8         | False            |
|         206014 | Wollomombi River at Coninside                |      370.1 |         28 |           126.9 |         1.299 | p99_train        | 26.2 x 30.9         | False            |

Threshold `p99_train` = 99th percentile of hourly maximum level over train hours (holdout excluded). `fits_16km_tile` matters only for map-based models with a 16 km tile.

## 5. Radar quality

|   catchment_id |   hours |   missing |   partial(<4 scans) |   low_coverage |   fill_code |   usable_% |
|---------------:|--------:|----------:|--------------------:|---------------:|------------:|-----------:|
|         201001 |   61920 |      1859 |                 481 |              7 |           0 |       96.2 |
|         203010 |   61920 |      1859 |                 481 |              6 |           0 |       96.2 |
|         203030 |   61920 |      1338 |                 533 |             14 |           0 |       97   |
|         204017 |   61920 |      1338 |                 533 |             27 |           1 |       96.9 |
|         204025 |   61920 |      1338 |                 533 |             23 |           1 |       96.9 |
|         204030 |   61920 |      1338 |                 533 |             14 |           0 |       97   |
|         204034 |   61920 |      1338 |                 533 |             12 |           0 |       97   |
|         204036 |   61920 |      1338 |                 533 |              6 |           0 |       97   |
|         204037 |   61920 |      1338 |                 533 |              7 |           0 |       97   |
|         204039 |   61920 |      1859 |                 481 |              1 |           0 |       96.2 |
|         204056 |   61920 |      1338 |                 533 |              9 |           0 |       96.5 |
|         204906 |   61920 |      1338 |                 533 |             27 |           4 |       96.9 |
|         206014 |   61920 |      1338 |                 533 |             20 |           0 |       97   |

Usable = all 4 scans, coverage ≥ 90%, no fill code (≥ 300 mm/h), no stuck maximum (≥ 6 h equal and ≥ 20 mm/h), outside manual exclusions.

Manual exclusions (`config.json → radar.qc_exclude`):

|   catchment_id | start_utc            | end_utc              | reason                                                                                                                                                                                                                  |
|---------------:|:---------------------|:---------------------|:------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|         204056 | 2024-04-08T00:00:00Z | 2024-04-21T00:00:00Z | Suspected radar/gauge-merge artefact: 10-17 mm/h catchment mean for ~8 days (987 mm in 72 h, about twice any other catchment) while the river peaked at only 1.96 m. Found with notebooks/inspect_data.ipynb section 5. |

## 6. River level

|   catchment_id |   hours_with_level_% |   max_level_m |
|---------------:|---------------------:|--------------:|
|         201001 |                 99.5 |          7.83 |
|         203010 |                 99.6 |         13.16 |
|         203030 |                 99.1 |          6.57 |
|         204017 |                 99.7 |          7.26 |
|         204025 |                100   |          6.2  |
|         204030 |                 99.9 |          1.98 |
|         204034 |                 99.8 |          2.86 |
|         204036 |                 99.8 |          4.91 |
|         204037 |                 99.7 |          3.56 |
|         204039 |                 99.8 |          6.01 |
|         204056 |                 99.9 |          3.18 |
|         204906 |                100   |         12.17 |
|         206014 |                 99.8 |          3.64 |

## 7. Flood onsets by split

| catchment_id   |   holdout |   test |   train |   val |   total |
|:---------------|----------:|-------:|--------:|------:|--------:|
| 201001         |         5 |     10 |      26 |     4 |      45 |
| 203010         |         6 |     11 |      22 |     3 |      42 |
| 203030         |         4 |      3 |      10 |     0 |      17 |
| 204017         |         4 |      6 |      25 |     2 |      37 |
| 204025         |         2 |      6 |      22 |     2 |      32 |
| 204030         |         4 |      3 |      20 |     0 |      27 |
| 204034         |         4 |      5 |      14 |     1 |      24 |
| 204036         |         5 |      7 |      11 |     0 |      23 |
| 204037         |         5 |      7 |      19 |     1 |      32 |
| 204039         |         6 |      4 |      13 |     0 |      23 |
| 204056         |         4 |     10 |      19 |     2 |      35 |
| 204906         |         3 |      3 |       9 |     1 |      16 |
| 206014         |         7 |      9 |      21 |     2 |      39 |
| ALL            |        59 |     84 |     231 |    18 |     392 |

Onset = first hour above threshold after ≥ 6 h below; a rise after fewer hours below is merged into the previous event.

## 8. Master table (shared/samples.csv)

| split   |      0 |    1 |   positive_% |
|:--------|-------:|-----:|-------------:|
| holdout |  11552 |  334 |         2.81 |
| test    | 103403 |  299 |         0.29 |
| train   | 368606 | 1088 |         0.29 |
| val     |  79354 |   72 |         0.09 |

Why candidate issue hours were dropped:

|   catchment_id |   candidate |   radar_gap |   level_gap |   in_flood |   kept |   kept_% |
|---------------:|------------:|------------:|------------:|-----------:|-------:|---------:|
|         201001 |       61843 |       16634 |         349 |        797 |  43979 |     71.1 |
|         203010 |       61843 |       16623 |         323 |        801 |  44042 |     71.2 |
|         203030 |       61843 |       17644 |         717 |       1062 |  42469 |     68.7 |
|         204017 |       61843 |       17986 |         243 |        865 |  42740 |     69.1 |
|         204025 |       61843 |       17829 |           7 |        780 |  43110 |     69.7 |
|         204030 |       61843 |       17229 |         110 |        527 |  43813 |     70.8 |
|         204034 |       61843 |       17423 |         173 |        727 |  43482 |     70.3 |
|         204036 |       61843 |       17218 |         123 |        652 |  43723 |     70.7 |
|         204037 |       61843 |       17226 |         291 |        786 |  43571 |     70.5 |
|         204039 |       61843 |       16623 |         202 |        619 |  44206 |     71.5 |
|         204056 |       61843 |       17668 |          95 |        894 |  43054 |     69.6 |
|         204906 |       61843 |       18033 |          16 |        691 |  42985 |     69.5 |
|         206014 |       61843 |       17403 |         169 |        754 |  43534 |     70.4 |

## 9. Known limitations

- Thresholds are statistical (p99), not official flood classes, unless entered in `label.manual_thresholds`.
- Radar: about 28% of issue hours are dropped because one bad hour blocks 72 issue times; plausibility review (notebook section 5) flags remaining suspect periods.
- The validation year (Jul 2023 - Jun 2024) is dry and has few events; the test period is dominated by early 2025.
- Soil water is modelled (AWRA-L, daily, ~5 km), not measured.
- Static attributes come from CAMELS-AUS and are fixed in time.