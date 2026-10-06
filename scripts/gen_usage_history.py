import csv
from pathlib import Path

import numpy as np

N = 3000
rng = np.random.default_rng(42)
OUT = Path(__file__).resolve().parent.parent / "data" / "usage_history.csv"

COUNTRY_GB = {"JP": 0.0, "KR": 0.1, "TH": 0.2}
USAGE_GB = {"map": 0.1, "social": 0.7, "video": 1.5}
SPECIAL_GB = {"none": 0.0, "work": 1.0, "light": -0.35}


def pick(options, p):
    return options[rng.choice(len(options), p=p)]


rows = []
for i in range(N):
    country = pick(list(COUNTRY_GB), [0.6, 0.25, 0.15])
    days = int(rng.integers(3, 9))
    density = round(float(np.clip(rng.normal(3.0, 0.9), 1.0, 6.0)), 1)
    usage = pick(list(USAGE_GB), [0.45, 0.35, 0.2])
    hotspot = "yes" if rng.random() < 0.25 else "no"
    special = pick(list(SPECIAL_GB), [0.75, 0.1, 0.15])

    gb = (0.45 + COUNTRY_GB[country] + 0.15 * (density - 2) + USAGE_GB[usage]
          + (0.6 if hotspot == "yes" else 0.0) + SPECIAL_GB[special]
          - 0.03 * (days - 3))                       # 天數越長，每天越省
    gb *= rng.lognormal(0, 0.18)                       # 個人差異
    gb = round(max(0.15, gb), 2)

    # 約四成用戶沒做快問快答
    skipped = rng.random() < 0.4
    rows.append({
        "order_id": f"o{i:05d}", "country": country, "days": days, "density": density,
        "usage": "" if skipped else usage, "hotspot": "" if skipped else hotspot,
        "special": "" if skipped else special, "daily_gb": gb,
    })

with OUT.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(f"寫入 {len(rows)} 筆 → {OUT}")
