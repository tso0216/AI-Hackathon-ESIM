from flask import Flask, jsonify, render_template, request, session

from config import Config
from services import advisor, qa, share, support
from services.ai_client import ai
from services.store import (
    PLANS, REVIEWS, SCENES, SPOTS, TRIP, apply_scene, fmt_dt, get_state, new_session_id, parse_dt,
    public_state, reset_state,
)

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
app.json.ensure_ascii = False


def current():
    if "sid" not in session:
        session["sid"] = new_session_id()
    return get_state(session["sid"])


def now_of(state):
    return parse_dt(state["now"])


def with_state(payload, state):
    payload["state"] = public_state(state)
    return jsonify(payload)


@app.get("/")
def index():
    return render_template("index.html")


# ---------- 狀態與情境 ----------
@app.get("/api/bootstrap")
def bootstrap():
    state = current()
    return with_state({
        "scenes": SCENES, "trip": TRIP, "spots": SPOTS, "plans": PLANS, "reviews": REVIEWS,
        "quiz": advisor.QUIZ, "ai": ai.status(),
        "quota": {"free": Config.FREE_QA_QUOTA, "esim": Config.ESIM_QA_QUOTA}, "now_label": fmt_dt(now_of(state)),
    }, state)


@app.post("/api/scene")
def scene():
    state = current()
    sc = apply_scene(state, request.json.get("scene"))
    if not sc:
        return jsonify({"error": "unknown scene"}), 400
    return with_state({"scene": sc, "now_label": fmt_dt(now_of(state))}, state)


@app.post("/api/state")
def update_state():
    """側欄的手動切換：回購者、是否已購 eSIM、重設額度等。"""
    state = current()
    body = request.json or {}
    if "returning" in body:
        state["returning"] = bool(body["returning"])
    if "has_esim" in body:
        if body["has_esim"]:
            _buy(state, "jp-2gb")
        else:
            state["has_esim"], state["esim"] = False, None
    if body.get("reset_quota"):
        state["qa_used"] = 0
    return with_state({}, state)


@app.post("/api/reset")
def reset():
    current()
    state = reset_state(session["sid"])
    return with_state({"now_label": fmt_dt(now_of(state))}, state)


# ---------- 解法 1：方案顧問 + 客服 ----------
@app.post("/api/advisor/recommend")
def recommend():
    state = current()
    return with_state(advisor.recommend(state, (request.json or {}).get("answers", {})), state)


@app.post("/api/checkout")
def checkout():
    state = current()
    plan = _buy(state, request.json["plan_id"])
    return with_state({"ok": True, "plan": plan}, state)


def _buy(state, plan_id):
    p = next(p for p in PLANS if p["id"] == plan_id)
    days = len(TRIP["days"])
    day_key = next((k for k in sorted(int(k) for k in p["prices"]) if k >= days), 7)
    state["has_esim"] = True
    state["esim"] = {"plan_id": p["id"], "name": p["name"], "days": day_key, "region": p["country"],
                     "price": p["prices"][str(day_key)], "daily_gb": p["daily_gb"], "unlimited": p["unlimited"]}
    return state["esim"]


@app.post("/api/support/chat")
def support_chat():
    state = current()
    body = request.json or {}
    return with_state(support.chat(body.get("message", ""), body.get("history")), state)


# ---------- 解法 2：經驗問答 ----------
@app.post("/api/qa/ask")
def qa_ask():
    state = current()
    body = request.json or {}
    return with_state(qa.ask(state, body.get("question", ""), body.get("spot_id"), now_of(state)), state)


@app.get("/api/spots/<spot_id>/reports")
def reports(spot_id):
    state = current()
    if spot_id not in SPOTS:
        return jsonify({"error": "unknown spot"}), 404
    return with_state({"reports": qa.latest_reports(spot_id, now_of(state))}, state)


# ---------- 解法 3：經驗換流量 ----------
@app.post("/api/share/transcribe")
def share_transcribe():
    state = current()
    audio = request.files.get("audio")
    spot_id = request.form.get("spot_id") or state["location"]
    data = audio.read() if audio else b""
    return with_state(share.transcribe(data, audio.filename if audio else "", spot_id,
                                       request.form.get("sample", "good")), state)


@app.post("/api/share/submit")
def share_submit():
    state = current()
    body = request.json or {}
    spot_id = body.get("spot_id") or state["location"]
    return with_state(share.submit(state, body.get("transcript", ""), spot_id, now_of(state)), state)


if __name__ == "__main__":
    print(f"AI 模式：{'LIVE（' + Config.LLM_MODEL + '）' if ai.live else 'MOCK（未設定 OPENAI_API_KEY）'}")
    app.run(debug=True, port=Config.PORT)
