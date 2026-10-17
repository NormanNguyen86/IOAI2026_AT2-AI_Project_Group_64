"""Candidate B: read the processed files and serve (X_dyn[72, F], X_static[S], y) per master-table row.

No 72-row copies are stored; each window is cut from the hourly table when asked for.

    from b_dataset import WindowDataset
    ds = WindowDataset(split="train")
    x_dyn, x_static, y = ds[0]           # numpy arrays
    X, XS, Y = ds.arrays()               # everything at once (careful with memory for 'train')

Works as a PyTorch Dataset too (it has __len__ and __getitem__).
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config.json").read_text())
B = ROOT / "data" / "processed" / "b"


class WindowDataset:
    def __init__(self, split=None):
        f = CFG["b_features"]
        self.dyn_names, self.static_names = f["dynamic"], f["static"]
        self.hist = CFG["time"]["history_hours"]
        s = pd.read_csv(ROOT / "shared" / "samples.csv", dtype={"catchment_id": str})
        self.samples = (s if split is None else s[s.split == split]).reset_index(drop=True)
        dyn = pd.read_parquet(B / "dynamic_hourly.parquet")
        self.series, self.t0 = {}, {}
        for cid, g in dyn.groupby("catchment_id"):
            g = g.sort_values("hour_end_utc")
            self.series[cid] = g[self.dyn_names].to_numpy(np.float32)
            self.t0[cid] = pd.Timestamp(g.hour_end_utc.iloc[0])
        st = pd.read_csv(B / "static.csv", dtype={"catchment_id": str}).set_index("catchment_id")
        self.static = {cid: st.loc[cid, self.static_names].to_numpy(np.float32) for cid in st.index}
        it = pd.to_datetime(self.samples.issue_utc, utc=True)
        self.end_idx = np.array([int((t - self.t0[c]) / pd.Timedelta(hours=1)) for c, t in zip(self.samples.catchment_id, it)])

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, i):
        cid, e = self.samples.catchment_id[i], self.end_idx[i]
        x = self.series[cid][e - self.hist + 1: e + 1]
        return x, self.static[cid], np.float32(self.samples.label[i])

    def arrays(self):
        X = np.stack([self[i][0] for i in range(len(self))])
        XS = np.stack([self[i][1] for i in range(len(self))])
        return X, XS, self.samples.label.to_numpy(np.float32)
