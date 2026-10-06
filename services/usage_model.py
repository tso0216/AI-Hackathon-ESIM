import csv
from pathlib import Path

import lightgbm as lgb
import numpy as np

DATA = Path(__file__).resolve().parent.parent / "data" / "usage_history.csv"

FEATURES = ["country", "days", "density", "usage", "hotspot", "special"]
CODES = {
    "country": {"JP": 0, "KR": 1, "TH": 2},
    "usage": {"map": 0, "social": 1, "video": 2},
    "hotspot": {"no": 0, "yes": 1},
    "special": {"none": 0, "work": 1, "light": 2},
}
CATEGORICAL = ["country", "usage", "special"]


def _encode(row):
    x = []
    for f in FEATURES:
        v = row.get(f)
        if f in CODES:
            x.append(CODES[f].get(v, np.nan) if v not in (None, "") else np.nan)
        else:
            x.append(float(v))
    return x


def _train():
    with DATA.open() as f:
        rows = list(csv.DictReader(f))
    X = np.array([_encode(r) for r in rows], dtype=float)
    y = np.array([float(r["daily_gb"]) for r in rows])
    ds = lgb.Dataset(X, y, feature_name=FEATURES, categorical_feature=CATEGORICAL)
    params = {"objective": "regression", "learning_rate": 0.05, "num_leaves": 15,
              "min_data_in_leaf": 20, "verbose": -1, "seed": 42}
    booster = lgb.train(params, ds, num_boost_round=300)
    return booster, len(rows)


MODEL, N_TRAIN = _train()


def predict(row):
    """回傳 (預估 GB/天, {特徵: SHAP 貢獻}, 基準值)。"""
    x = np.array([_encode(row)], dtype=float)
    contrib = MODEL.predict(x, pred_contrib=True)[0]
    shap = dict(zip(FEATURES, contrib[:-1]))
    base = float(contrib[-1])
    return float(contrib.sum()), shap, base
