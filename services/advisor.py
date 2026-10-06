import json

from services.ai_client import ai
from services import usage_model
from services.store import PLANS, SPOTS, TRIP
from services.trace import Trace

SAFETY = 1.15  # 安全係數：估算值再多留 15%，避免斷網

USAGE_LABELS = {"map": "地圖、查資料為主", "social": "常發 IG 限動、照片", "video": "看影片、視訊或直播"}
SPECIAL_LABELS = {"none": "沒有", "work": "需要遠端工作、視訊會議", "light": "盡量省，有 Wi-Fi 就用 Wi-Fi"}

FACTOR_LABELS = {
    "usage": {"map": "地圖為主", "social": "發限動", "video": "影片視訊"},
    "special": {"none": "無特殊需求", "work": "遠端工作", "light": "盡量省"},
}

QUIZ = [
    {"key": "hotspot", "q": "會開熱點分享給朋友嗎？", "options": [["yes", "會，常和朋友共用"], ["no", "不會，自己用就好"]]},
    {"key": "usage", "q": "網路主要拿來做什麼？", "options": [["map", "地圖、查資料"], ["social", "常發 IG 限動"], ["video", "看影片、視訊"]]},
    {"key": "special", "q": "有特殊需求嗎？", "options": [["none", "沒有"], ["work", "要遠端工作"], ["light", "盡量省流量"]]},
]


def trip_features(trip=TRIP):
    days = len(trip["days"])
    spots = sum(len(d["items"]) for d in trip["days"])
    return {"country": trip["country"], "days": days, "spots": spots, "density": round(spots / days, 1)}


def estimate_usage(feat, answers, past_daily_gb=None):
    """每日用量估算：LightGBM 模型（用 data/usage_history.csv 的歷史訂單訓練，目前為 mock 資料）。

    contributions 為 SHAP 值：基準（歷史平均）＋各特徵的加減，總和＝模型預估。
    """
    row = {"country": feat["country"], "days": feat["days"], "density": feat["density"], **answers}
    model_est, shap, base = usage_model.predict(row)

    labels = {
        "country": f"目的地 {feat['country']}",
        "days": f"{feat['days']} 天行程",
        "density": f"每天 {feat['density']} 個景點",
        "usage": FACTOR_LABELS["usage"].get(answers.get("usage"), "用途未作答"),
        "hotspot": "開熱點" if answers.get("hotspot") == "yes" else "不開熱點",
        "special": FACTOR_LABELS["special"].get(answers.get("special"), "需求未作答"),
    }
    contrib = [("歷史平均", round(base, 2), "base")]
    other = 0.0
    for key, v in shap.items():
        answered = key not in ("usage", "hotspot", "special") or answers.get(key)
        if abs(v) >= 0.05 and answered:
            contrib.append((labels[key], round(float(v), 2), key))
        else:
            other += v
    if abs(other) >= 0.01:
        contrib.append(("其他", round(float(other), 2), "other"))

    model_est = round(max(0.3, model_est), 2)
    est = model_est
    if past_daily_gb:
        # 回購者：上次實際用量權重較高
        est = round(0.4 * model_est + 0.6 * past_daily_gb, 2)
        contrib.append((f"上次 {past_daily_gb}GB/天", round(est - model_est, 2), "past"))

    return est, [{"factor": f, "gb": v, "key": k} for f, v, k in contrib]


def match_plans(country, days, est):
    need = est * SAFETY
    day_keys = sorted(int(k) for k in PLANS[0]["prices"])
    day_key = next((k for k in day_keys if k >= days), day_keys[-1])
    plans = [p for p in PLANS if p["country"] == country]
    fixed = sorted([p for p in plans if not p["unlimited"]], key=lambda p: p["daily_gb"])
    pick = next((p for p in fixed if p["daily_gb"] >= need), None) or next(p for p in plans if p["unlimited"])

    def view(p, tag):
        return {"id": p["id"], "name": p["name"], "daily_gb": p["daily_gb"], "unlimited": p["unlimited"],
                "days": day_key, "price": p["prices"][str(day_key)], "tag": tag, "throttle": p["throttle"]}

    ordered = fixed + [p for p in plans if p["unlimited"]]
    idx = ordered.index(pick)
    alts = []
    if idx > 0:
        alts.append(view(ordered[idx - 1], "省錢"))
    if idx < len(ordered) - 1:
        alts.append(view(ordered[idx + 1], "加量"))
    return view(pick, "推薦"), alts, round(need, 2), day_key


def recommend(state, answers):
    tr = Trace("解法 1｜AI 方案顧問")
    feat = trip_features()
    past = state["past_daily_gb"] if state["returning"] else None

    tr.add("輸入資料", "rule", {
        "去趣行程": f"{TRIP['title']}・{feat['days']} 天・{feat['spots']} 個景點",
        "過往用量": f"{past}GB/天" if past else "無（新用戶）",
        "三題快問快答": _answers_text(answers) or "未作答",
    })

    est, contrib = estimate_usage(feat, answers, past)
    tr.add("1 用量估算", "LightGBM", {"訓練資料": f"{usage_model.N_TRAIN} 筆歷史訂單（mock）",
                                     "每日預估": f"{est}GB", "因素貢獻（SHAP）": contrib})

    plan, alts, need, day_key = match_plans(feat["country"], feat["days"], est)
    tr.add("2 方案比對", "rule", {
        "需求": f"{est}GB × 安全係數 {SAFETY} = {need}GB/天，{feat['days']} 天 → 選 {day_key} 天方案",
        "推薦": f"{plan['name']} × {plan['days']} 天 NT${plan['price']}",
        "備選": [f"{a['name']} NT${a['price']}（{a['tag']}）" for a in alts],
    })

    top_factors = sorted([c for c in contrib if c["gb"] > 0 and c["key"] != "base"], key=lambda c: -c["gb"])[:2]

    def fallback():
        personal = [c["factor"] for c in contrib if c["gb"] > 0 and c["key"] in ("usage", "hotspot", "special")]
        why = "".join(f"＋{f}" for f in personal[:2])
        size = "吃到飽" if plan["unlimited"] else f"{plan['daily_gb']}GB"
        return {"reason": f"{feat['spots']} 個景點{why}，每日約 {est}GB，{size}剛好。"}

    system = (
        "你是去趣 eSIM 的方案顧問。用繁體中文寫一句 25 字以內的推薦理由，"
        "提到行程特點與每日預估用量，不要編造方案規格。"
        '輸出 JSON：{"reason": "..."}'
    )
    user = json.dumps({
        "行程": {"標題": TRIP["title"], "天數": feat["days"], "景點數": feat["spots"],
                 "景點": [SPOTS[i["spot_id"]]["name"] for d in TRIP["days"] for i in d["items"]][:8]},
        "使用習慣": _answers_text(answers) or "未作答",
        "每日預估用量GB": est,
        "主要因素": [c["factor"] for c in top_factors],
        "推薦方案": plan,
        "方案規格": next(p for p in PLANS if p["id"] == plan["id"]),
    }, ensure_ascii=False)
    out, mode = ai.chat_json(system, user, fallback)
    tr.add("3 推薦理由生成", mode, {"輸出": out})

    return {"estimate_gb": est, "contributions": contrib, "plan": plan, "alternatives": alts,
            "reason": out.get("reason", ""), "answered": bool(answers),
            "trace": tr.to_dict()}


def _answers_text(answers):
    parts = []
    if answers.get("hotspot"):
        parts.append("會開熱點" if answers["hotspot"] == "yes" else "不開熱點")
    if answers.get("usage"):
        parts.append(USAGE_LABELS[answers["usage"]])
    if answers.get("special") and answers["special"] != "none":
        parts.append(SPECIAL_LABELS[answers["special"]])
    return "、".join(parts)

