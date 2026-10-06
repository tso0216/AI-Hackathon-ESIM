import json
import re
import uuid

from config import Config
from services.ai_client import ai, cosine
from services.store import SPOTS, SPOT_COUNTRY, TRIP, add_experience, experiences, fmt_dt, parse_dt, time_slot
from services.trace import Trace

# 沒有麥克風或沒有 ASR 時用的範例逐字稿
SAMPLES = {
    "usj_nintendo": {
        "good": "任天堂區現在入區排隊大概 90 分鐘，整理券已經發完了，建議直接買快速通關。",
        "bad": "哈哈哈哈隨便亂講，哈哈哈",
    },
    "arashiyama": {
        "good": "嵐山竹林現在下小雨，人不多，入口排大概五分鐘，石板路有點滑記得穿防滑鞋。",
        "bad": "哈哈哈哈隨便亂講，哈哈哈",
    },
}
DEFAULT_SAMPLE = {"good": "現在人潮還好，排隊大概 10 分鐘，拍照不用等太久。", "bad": "哈哈哈哈隨便亂講，哈哈哈"}

BANNED = ["幹", "白痴", "垃圾", "詐騙", "加我line", "加賴"]
SPECIFIC_WORDS = r"排|等|分鐘|小時|人|擠|空|雨|雪|晴|滑|冷|熱|整理券|快速通關|票|開|關|收|好拍|拍照|推薦|建議|好吃|停駛|班次|\d"


def sample_transcript(spot_id, kind="good"):
    return SAMPLES.get(spot_id, DEFAULT_SAMPLE)[kind]


def transcribe(audio_bytes, filename, spot_id, sample_kind="good"):
    tr = Trace("解法 3｜語音轉文字")
    text, mode = ai.transcribe(audio_bytes, filename, lambda: sample_transcript(spot_id, sample_kind))
    tr.add("1 語音轉文字（ASR）", mode, {
        "音檔": f"{filename}（{len(audio_bytes or b'') // 1024} KB）" if audio_bytes else "無音檔，使用範例逐字稿",
        "逐字稿": text,
    })
    return {"transcript": text, "trace": tr.to_dict()}


def _structure_rule(transcript, spot_id, now):
    t = transcript
    cat = "一般"
    for key, pat in [("排隊", r"排|等|整理券|快速通關"), ("天氣", r"雨|雪|滑|冷|熱"), ("人潮", r"人|擠|空"),
                     ("美食", r"吃|好吃|店"), ("交通", r"車|班次|停駛|站")]:
        if re.search(pat, t):
            cat = key
            break
    wait = re.search(r"(\d+)\s*分", t)
    summary = re.sub(r"^(嗯+|呃+|那個)[，,]?", "", t).strip("。 ")
    summary = "，".join(summary.split("，")[:2])[:30]
    return {"spot_id": spot_id, "time": now.isoformat(timespec="minutes"), "time_slot": time_slot(now),
            "category": cat, "wait_minutes": int(wait.group(1)) if wait else None, "summary": summary}


def _review_rule(transcript):
    t = transcript.replace(" ", "")
    laugh_ratio = len(re.findall(r"[哈呵嘿笑]", t)) / max(1, len(t))
    specific = len(re.findall(SPECIFIC_WORDS, t))
    bad = [w for w in BANNED if w in t.lower()]
    relevant = len(t) >= 8 and laugh_ratio < 0.3 and specific >= 1
    return {"relevant": relevant, "specific": specific >= 2, "inappropriate": bool(bad),
            "reason": "有具體現場狀況" if relevant and specific >= 2 else "內容無關"}


def submit(state, transcript, spot_id, now):
    tr = Trace("解法 3｜經驗換流量")
    spot = SPOTS[spot_id]

    # 2 結構化整理
    system = (
        "把旅客口述的現場經驗整理成結構化資料。輸出 JSON："
        '{"spot_id": "...", "time": "ISO 時間", "time_slot": "早上|中午|下午|晚上", '
        '"category": "人潮|排隊|天氣|交通|美食|拍照|設施|一般", "wait_minutes": 數字或 null, '
        '"summary": "20 字以內、去除贅字與個資的繁體中文摘要"}'
    )
    user = json.dumps({"逐字稿": transcript, "spot_id": spot_id, "景點": spot["name"], "now": now.isoformat()},
                      ensure_ascii=False)
    data, smode = ai.chat_json(system, user, lambda: _structure_rule(transcript, spot_id, now))
    data["spot_id"] = spot_id
    data["time"] = now.isoformat(timespec="minutes")
    tr.add("2 結構化整理", smode, {"逐字稿": transcript, "輸出": data})

    # 3 品質審核與驗證
    checks = []
    region_ok = state["has_esim"] and state["esim"] and state["esim"]["region"] == SPOT_COUNTRY[spot_id]
    checks.append({"name": "eSIM 在場", "passed": bool(region_ok),
                   "detail": f"啟用地區 {state['esim']['region']}" if region_ok else "需使用去趣 eSIM"})

    trip_start = parse_dt(TRIP["start"] + "T00:00")
    trip_end = parse_dt(TRIP["end"] + "T23:59")
    in_trip = trip_start <= now <= trip_end and state.get("location") == spot_id
    checks.append({"name": "時間地點", "passed": in_trip,
                   "detail": fmt_dt(now) if in_trip else "與行程不符"})

    judge_system = (
        "你是旅遊經驗審核員。判斷旅客口述內容：relevant＝是否與該景點的現場狀況有關；"
        "specific＝是否有具體資訊（時間、排隊、人潮、天氣、建議等）；inappropriate＝是否含不當、廣告或個資。"
        '輸出 JSON：{"relevant": bool, "specific": bool, "inappropriate": bool, "reason": "10 字以內"}'
    )
    judge, jmode = ai.chat_json(judge_system, json.dumps({"景點": spot["name"], "內容": transcript}, ensure_ascii=False),
                                lambda: _review_rule(transcript))
    content_ok = bool(judge.get("relevant")) and bool(judge.get("specific"))
    checks.append({"name": "內容具體", "passed": content_ok, "detail": judge.get("reason", "")})
    checks.append({"name": "無不當內容", "passed": not judge.get("inappropriate"),
                   "detail": "" if not judge.get("inappropriate") else "含不當或廣告"})

    recent = [e for e in experiences() if e["spot_id"] == spot_id
              and 0 <= (now - parse_dt(e["time"])).total_seconds() <= 6 * 3600]
    dup_score = 0.0
    if recent and content_ok:
        vecs, _ = ai.embed([data["summary"]] + [e["summary"] for e in recent])
        dup_score = max(cosine(vecs[0], v) for v in vecs[1:])
    dup_ok = dup_score < 0.92
    checks.append({"name": "不重複", "passed": dup_ok,
                   "detail": f"相似度 {dup_score:.2f}" if dup_ok else "與近期回報重複"})

    already = any(c["spot_id"] == spot_id and c["date"] == now.date().isoformat() for c in state["cards"])
    tr.add("3 品質審核與驗證", jmode, {"檢查": checks})

    passed = all(c["passed"] for c in checks)
    reward = 0
    exp = None
    if passed:
        exp = {"id": "u" + uuid.uuid4().hex[:8], "spot_id": spot_id, "time": data["time"],
               "weather": "雨" if "雨" in transcript else "晴", "category": data.get("category", "一般"),
               "summary": data.get("summary", transcript[:40]), "source": "traveler", "verified": True}
        add_experience(exp)
        state["shared"].append(exp["id"])
        if not already:
            reward = Config.SHARE_REWARD_MB
            state["bonus_mb"] += reward
        state["app_bound"] = True
        state["cards"].append({"spot_id": spot_id, "spot_name": spot["name"], "date": now.date().isoformat(),
                               "time": fmt_dt(now), "summary": exp["summary"], "category": exp["category"],
                               "reward_mb": reward})
        tr.add("4 入庫並發放獎勵", "rule", {"經驗 id": exp["id"],
                                         "流量加碼": f"+{reward}MB" if reward else "同景點同日已領過，不重複發放",
                                         "App 綁定": "完成"})
    else:
        tr.add("4 不入庫", "rule", {"未通過": [c["name"] for c in checks if not c["passed"]]})

    return {"passed": passed, "checks": checks, "structured": data, "experience": exp, "reward_mb": reward,
            "trace": tr.to_dict()}
