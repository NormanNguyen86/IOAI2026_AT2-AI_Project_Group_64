"""Step 8: write data/report.md: what was collected, from where, its quality, and what the master table contains."""
import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import shape
from shapely import transform as shp_transform
from common import CFG, DATA, INTERIM, SHARED, MANIFEST, catchments, log, split_of, utc, radar_good

STEP = "s08"


def md(df, index=False):
    return df.to_markdown(index=index)


def main():
    cat = catchments()
    ev = pd.read_csv(SHARED / "events.csv", dtype={"catchment_id": str}, parse_dates=["onset_utc", "end_utc"])
    s = pd.read_csv(SHARED / "samples.csv", dtype={"catchment_id": str})
    man = pd.read_csv(MANIFEST)
    fs = pd.read_csv(INTERIM / "samples_filter_stats.csv", dtype={"catchment_id": str})
    hours = pd.date_range(utc(CFG["period"]["start_utc"]), utc(CFG["period"]["end_utc"]), freq="1h")
    R, L = CFG["radar"], CFG["label"]

    # catchment extent on the shared metric grid (for map-based candidates)
    to_alb = Transformer.from_crs("EPSG:4326", "EPSG:3577", always_xy=True)
    ext = {}
    for f in json.loads((SHARED / "boundaries.geojson").read_text())["features"]:
        g = shp_transform(shape(f["geometry"]), lambda xy: np.column_stack(to_alb.transform(xy[:, 0], xy[:, 1])))
        x0, y0, x1, y1 = g.bounds
        ext[f["properties"]["catchment_id"]] = (round((x1 - x0) / 1e3, 1), round((y1 - y0) / 1e3, 1))
    ct = cat[["catchment_id", "name", "area_km2", "radar_id", "radar_dist_km", "threshold_m", "threshold_type"]].copy()
    ct["extent_km (w x h)"] = ct.catchment_id.map(lambda c: f"{ext[c][0]} x {ext[c][1]}")
    ct["fits_16km_tile"] = ct.catchment_id.map(lambda c: max(ext[c]) <= 16)

    # radar quality
    rq = []
    for c in cat.itertuples():
        r = pd.read_csv(INTERIM / "radar" / f"radar{c.radar_id}_hourly.csv", dtype={"catchment_id": str})
        r = r[r.catchment_id == c.catchment_id]; r.index = pd.to_datetime(r.hour_end_utc, utc=True); r = r.sort_index()
        good = radar_good(r).reindex(hours, fill_value=False)
        r = r.reindex(hours)
        rq.append({"catchment_id": c.catchment_id, "hours": len(hours), "missing": int(r.n15.isna().sum()),
                   "partial(<4 scans)": int((r.n15 < R["min_scans_per_hour"]).sum()),
                   "low_coverage": int((r.coverage < R["min_coverage"]).sum()),
                   "fill_code": int((r.rain_max >= R["qc_max_mm_per_hour"]).sum()),
                   "usable_%": round(100 * good.mean(), 1)})
    rq = pd.DataFrame(rq)

    # river level completeness
    lc = []
    for c in cat.catchment_id:
        lv = pd.read_csv(INTERIM / "levels" / f"{c}.csv", index_col=0, parse_dates=True).level_max_m.reindex(hours)
        lc.append({"catchment_id": c, "hours_with_level_%": round(100 * lv.notna().mean(), 1), "max_level_m": round(lv.max(), 2)})
    lc = pd.DataFrame(lc)

    ev["split"] = split_of(pd.DatetimeIndex(ev.onset_utc))
    ev_tab = ev.pivot_table(index="catchment_id", columns="split", values="onset_utc", aggfunc="count", fill_value=0)
    ev_tab["total"] = ev_tab.sum(axis=1); ev_tab.loc["ALL"] = ev_tab.sum()
    lab = s.groupby(["split", "label"]).size().unstack(fill_value=0)
    lab["positive_%"] = (100 * lab[1] / lab.sum(axis=1)).round(2)
    man["host"] = man.url.str.extract(r"https?://([^/]+)")
    src = man.groupby(["step", "host"]).agg(requests=("url", "size"), ok=("status", lambda x: int((x == 200).sum())),
                                             not_found=("status", lambda x: int((x == 404).sum())),
                                             GB=("bytes", lambda x: round(x.sum() / 1e9, 3)),
                                             first=("retrieved_utc", "min"), last=("retrieved_utc", "max")).reset_index()
    excl = pd.DataFrame(R.get("qc_exclude", [])) if R.get("qc_exclude") else pd.DataFrame(columns=["catchment_id", "start_utc", "end_utc", "reason"])
    fs["kept_%"] = (100 * fs.kept / fs.candidate).round(1)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Data report", "",
        f"Generated {now} by `steps/s08_report.py` from the files in this folder. Regenerate with `python run_all.py --only 8`.",
        "For charts and a discussion of every table, open `notebooks/inspect_data.ipynb`.", "",
        "## 1. Summary", "",
        f"- Study area: {CFG['study_area']['name']}; radars: " + ", ".join(f"{k} ({v})" for k, v in CFG['study_area']['radars'].items()) + ".",
        f"- Period: {CFG['period']['start_utc']} to {CFG['period']['end_utc']} (UTC), {len(hours):,} hours.",
        f"- {len(cat)} catchments, {len(ev)} flood onsets, {len(s):,} scored samples ({int(s.label.sum()):,} positive).",
        f"- Target: flood onset at the outlet gauge in (issue, issue + {CFG['time']['horizon_hours']} h]; inputs use up to {CFG['time']['history_hours']} h before the issue time.",
        "",
        "## 2. Sources (from data/manifest.csv)", "", md(src), "",
        f"{len(man):,} requests are logged with URL, time, size and SHA-256. HTTP 404 = the file does not exist at the provider (radar days missing on NCI).", "",
        "## 3. Split", "",
        md(pd.DataFrame([{"set": k, "from": v[0], "to": v[1]} for k, v in CFG["split"].items() if k in ("train", "val", "test", "holdout")])),
        f"\nIssue times within {CFG['split']['gap_hours']} h of a split change are dropped (except holdout), so no input or label window crosses sets.", "",
        "## 4. Catchments", "", md(ct), "",
        f"Threshold `p99_train` = {L['fallback_percentile']}th percentile of hourly maximum level over train hours (holdout excluded). "
        "`fits_16km_tile` matters only for map-based models with a 16 km tile.", "",
        "## 5. Radar quality", "", md(rq), "",
        f"Usable = all {R['min_scans_per_hour']} scans, coverage ≥ {R['min_coverage']:.0%}, no fill code (≥ {R['qc_max_mm_per_hour']} mm/h), "
        f"no stuck maximum (≥ {R['qc_stuck_hours']} h equal and ≥ {R['qc_stuck_min_mm']} mm/h), outside manual exclusions.", "",
        "Manual exclusions (`config.json → radar.qc_exclude`):", "", md(excl) if len(excl) else "_none_", "",
        "## 6. River level", "", md(lc), "",
        "## 7. Flood onsets by split", "", md(ev_tab.reset_index()), "",
        f"Onset = first hour above threshold after ≥ {L['onset_min_hours_below']} h below; a rise after fewer hours below is merged into the previous event.", "",
        "## 8. Master table (shared/samples.csv)", "", md(lab.reset_index()), "",
        "Why candidate issue hours were dropped:", "", md(fs), "",
        "## 9. Known limitations", "",
        "- Thresholds are statistical (p99), not official flood classes, unless entered in `label.manual_thresholds`.",
        "- Radar: about 28% of issue hours are dropped because one bad hour blocks 72 issue times; plausibility review (notebook section 5) flags remaining suspect periods.",
        "- The validation year (Jul 2023 - Jun 2024) is dry and has few events; the test period is dominated by early 2025.",
        "- Soil water is modelled (AWRA-L, daily, ~5 km), not measured.",
        "- Static attributes come from CAMELS-AUS and are fixed in time.",
    ]
    (DATA / "report.md").write_text("\n".join(lines))
    log(STEP, "data/report.md written")


if __name__ == "__main__":
    main()
