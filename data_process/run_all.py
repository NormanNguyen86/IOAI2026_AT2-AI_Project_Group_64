"""Run the pipeline steps in order.

    python run_all.py              # all steps
    python run_all.py --from 4     # resume from step 4 (radar is itself resumable)
    python run_all.py --only 6 7   # just these steps
"""
import argparse, runpy, sys, time
from pathlib import Path

STEPS = {1: "s01_catchments", 2: "s02_levels", 3: "s03_events", 4: "s04_radar",
         5: "s05_soil", 6: "s06_samples", 7: "s07_build_b", 8: "s08_report"}

ap = argparse.ArgumentParser()
ap.add_argument("--from", dest="start", type=int, default=1)
ap.add_argument("--only", type=int, nargs="*")
a = ap.parse_args()
here = Path(__file__).resolve().parent / "steps"
sys.path.insert(0, str(here))
for k in (a.only or [k for k in STEPS if k >= a.start]):
    t = time.time()
    print(f"=== step {k}: {STEPS[k]} ===", flush=True)
    sys.argv = [STEPS[k]]
    runpy.run_path(str(here / f"{STEPS[k]}.py"), run_name="__main__")
    print(f"=== step {k} done in {time.time() - t:.0f}s ===", flush=True)
