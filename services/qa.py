import json
import math
import re

from services.ai_client import ai, cosine
from services.store import SPOTS, ago_label, day_type, experiences, parse_dt, time_slot
from services.trace import Trace

TOP_K = 5
MIN_SCORE = 0.42
SLOTS = ["早上", "中午", "下午", "晚上"]


# ---------- 1 問題解析 ----------
def parse_question_rule(question, ctx_spot, now):
    q = question
    spot = None
    for sid, s in SPOTS.items():
        if any(a.lower() in q.lower() for a in s["aliases"]):
            spot = sid
            break
    spot = spot or ctx_spot

    live = bool(re.search(r"現在|目前|此刻|剛剛|這時候", q))
    m = re.search(r"(\d{1,2})\s*月", q)
    month = int(m.group(1)) if m else (now.month if live else None)

    dtype = None
    if re.search(r"週末|周末|假日|週六|週日|周六|周日|星期六|星期日|禮拜六|禮拜天", q):
        dtype = "週末"
    elif re.search(r"平日|週[一二三四五]|星期[一二三四五]|上班日", q):
        dtype = "平日"
    elif live:
        dtype = day_type(now)

    slot = None
    if re.search(r"清晨|一早|早上|上午|早晨|開門", q):
        slot = "早上"
    elif re.search(r"中午|午餐", q):
        slot = "中午"
    elif re.search(r"下午", q):
        slot = "下午"
    elif re.search(r"傍晚|晚上|夜|夕陽", q):
        slot = "晚上"
    elif live:
        slot = time_slot(now)

    weather = "雨" if re.search(r"雨", q) else ("雪" if "雪" in q else None)

    aspect = "一般"
    for key, pat in [("排隊", r"排隊|排多久|等多久|要等"), ("人潮", r"人多|人少|擠|人潮|人很多"),
                     ("拍照", r"拍照|好拍|拍"), ("美食", r"吃|美食|好吃"), ("交通", r"交通|怎麼去|車站|停駛"),
                     ("天氣", r"雨|雪|熱|冷|滑")]:
        if re.search(pat, q):
            aspect = key
            break
    return {"spot_id": spot, "month": month, "day_type": dtype, "time_slot": slot,
            "weather": weather, "aspect": aspect, "live": live}


def parse_question(question, ctx_spot, now):
    def fallback():
        return parse_question_rule(question, ctx_spot, now)

    system = (
        "從旅客的問題抽出查詢條件，輸出 JSON："
        '{"spot_id": 景點 id 或 null, "month": 1-12 或 null, "day_type": "平日"|"週末"|null, '
        '"time_slot": "早上"|"中午"|"下午"|"晚上"|null, "weather": "雨"|"雪"|null, '
        '"aspect": "人潮"|"排隊"|"拍照"|"美食"|"交通"|"天氣"|"一般", "live": 是否在問「現在」的狀況}。'
        "問題沒提到景點就用 context_spot；live 為 true 時，月份、平日/週末、時段依 now 推算。"
    )
    user = json.dumps({
        "question": question, "context_spot": ctx_spot, "now": now.isoformat(),
        "spots": {sid: s["aliases"] for sid, s in SPOTS.items()},
    }, ensure_ascii=False)
    out, mode = ai.chat_json(system, user, fallback)
    if out.get("spot_id") not in SPOTS:
        out["spot_id"] = ctx_spot
    return out, mode


# ---------- 2 檢索 ----------
def _month_score(m1, m2):
    if m1 is None:
        return 0.5
    d = min(abs(m1 - m2), 12 - abs(m1 - m2))
    return 1.0 if d == 0 else (0.5 if d == 1 else 0.0)


def retrieve(question, cond, now):
    """先依地點、時間（不能是未來）過濾，再依語意相似度 + 時空條件 + 新近度排序。

    正式版：WHERE spot_id=… AND time<=now 交給 PostgreSQL，語意相似度用 pgvector 的 <=> 運算子。
    """
    cands = [e for e in experiences() if e["spot_id"] == cond["spot_id"] and parse_dt(e["time"]) <= now]
    if not cands:
        return [], "rule", 0
    vecs, emode = ai.embed([question] + [f"{SPOTS[e['spot_id']]['name']} {e['category']} {e['summary']}" for e in cands])
    q = vecs[0]
    scored = []
    for e, v in zip(cands, vecs[1:]):
        t = parse_dt(e["time"])
        age_days = (now - t).total_seconds() / 86400
        sem = max(0.0, cosine(q, v))
        s_slot = 1.0 if cond.get("time_slot") in (None, time_slot(t)) else (
            0.4 if cond.get("time_slot") and abs(SLOTS.index(cond["time_slot"]) - SLOTS.index(time_slot(t))) == 1 else 0.0)
        s_day = 1.0 if cond.get("day_type") in (None, day_type(t)) else 0.0
        s_month = _month_score(cond.get("month"), t.month)
        s_weather = 1.0 if cond.get("weather") in (None, e["weather"]) else 0.0
        recency = math.exp(-age_days / 365)
        score = 0.25 * sem + 0.2 * s_slot + 0.12 * s_day + 0.15 * s_month + 0.1 * s_weather + 0.13 * recency
        score += 0.05 if e["verified"] else 0.0
        if cond.get("live") and age_days <= 0.25:  # 6 小時內的現場回報
            score += 0.3
        scored.append({**e, "score": round(score, 3), "sem": round(sem, 3), "ago": ago_label(t, now)})
    scored.sort(key=lambda x: -x["score"])
    hits = [h for h in scored if h["score"] >= MIN_SCORE][:TOP_K]
    return hits, emode, len(cands)


# ---------- 3 回答生成 ----------
def ask(state, question, ctx_spot, now):
    from config import Config

    tr = Trace("解法 2｜時空經驗問答")
    quota = Config.ESIM_QA_QUOTA if state["has_esim"] else Config.FREE_QA_QUOTA
    if state["qa_used"] >= quota:
        tr.add("額度檢查", "rule", {"已用": state["qa_used"], "額度": quota, "結果": "額度用完 → 引導購買 eSIM"})
        return {"quota_exceeded": True, "trace": tr.to_dict()}

    cond, pmode = parse_question(question, ctx_spot, now)
    tr.add("1 問題解析", pmode, {"問題": question, "抽出條件": {**cond, "spot_name": SPOTS[cond["spot_id"]]["name"] if cond.get("spot_id") else None}})

    if not cond.get("spot_id"):
        return _refuse(state, tr, "是哪個景點呢？", cond, invite=False)

    hits, emode, n = retrieve(question, cond, now)
    tr.add("2 資料檢索（RAG）", emode, {
        "候選": f"{SPOTS[cond['spot_id']]['name']} 共 {n} 則（排除未來時間）",
        "排序": "0.25 語意 + 0.2 時段 + 0.12 平日/週末 + 0.15 月份 + 0.1 天氣 + 0.13 新近度 + 驗證加分（現場模式 6 小時內 +0.3）",
        "命中": [{"摘要": h["summary"], "時間": h["time"], "分數": h["score"]} for h in hits],
        "門檻": MIN_SCORE,
    })

    if len(hits) < 1:
        return _refuse(state, tr, "還沒有相關經驗，已邀請現場旅人補充。", cond, invite=True)

    def fallback():
        return {"answer": _mock_answer(hits, cond), "enough": True}

    system = (
        "你是去趣的旅遊經驗助理。只能根據提供的旅人經驗，用繁體中文回答旅客的問題，30 字以內，"
        "給出具體時間、排隊分鐘數等細節；經驗之間有衝突時以較新、與提問時段相符的為準。"
        "經驗不足以回答時 enough 設 false。不要編造經驗裡沒有的資訊。"
        '輸出 JSON：{"answer": "...", "enough": true}'
    )
    user = json.dumps({
        "question": question, "now": now.isoformat(), "條件": cond,
        "旅人經驗": [{"時間": h["time"], "天氣": h["weather"], "內容": h["summary"], "多久前": h["ago"]} for h in hits],
    }, ensure_ascii=False)
    out, gmode = ai.chat_json(system, user, fallback)
    tr.add("3 回答生成", gmode, {"輸出": out})

    if not out.get("enough", True):
        return _refuse(state, tr, "經驗不足，已邀請現場旅人補充。", cond, invite=True)

    state["qa_used"] += 1
    newest = min(hits, key=lambda h: (now - parse_dt(h["time"])).total_seconds())
    newest_age = now - parse_dt(newest["time"])
    n_today = sum(1 for h in hits if (now - parse_dt(h["time"])).total_seconds() < 86400)
    if n_today:
        meta = f"{n_today} 則現場・{newest['ago']}"
    elif cond.get("live"):
        meta = f"{len(hits)} 則歷史經驗"
    elif newest_age.days <= 365:
        meta = f"{len(hits)} 則經驗・近一年"
    else:
        meta = f"{len(hits)} 則經驗"
    tr.add("4 後續引導", "rule", {"剩餘額度": quota - state["qa_used"]})
    return {"answer": out.get("answer", ""), "meta": meta, "sources": hits, "cond": cond,
            "refused": False, "trace": tr.to_dict()}


def _refuse(state, tr, msg, cond, invite):
    tr.add("拒答", "rule", {"原因": msg, "邀請現場旅人補充": invite})
    return {"answer": msg, "meta": "", "sources": [], "cond": cond, "refused": True, "invite": invite,
            "trace": tr.to_dict()}


def _mock_answer(hits, cond):
    """沒有 LLM 時，回傳與提問面向最相符的那一則經驗。"""
    ordered = sorted(hits, key=lambda h: h["category"] != cond.get("aspect"))
    return ordered[0]["summary"] + "。"


def latest_reports(spot_id, now, hours=24):
    out = []
    for e in experiences():
        t = parse_dt(e["time"])
        if e["spot_id"] == spot_id and 0 <= (now - t).total_seconds() <= hours * 3600:
            out.append({**e, "ago": ago_label(t, now)})
    return sorted(out, key=lambda e: e["time"], reverse=True)
