import copy
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

from config import Config

DATA = Path(__file__).resolve().parent.parent / "data"


def _load(name):
    with open(DATA / name, encoding="utf-8") as f:
        return json.load(f)


TRIP = _load("trip.json")
SPOTS = {s["id"]: s for s in _load("spots.json")}
PLANS = _load("plans.json")
FAQ = _load("faq.json")
REVIEWS = _load("reviews.json")
SEED_EXPERIENCES = _load("experiences.json")

SPOT_COUNTRY = {sid: "JP" for sid in SPOTS}  # demo 只有日本

# 示範情境：左側選單切換時套用，決定「現在時間」「目前位置」與要顯示的畫面
SCENES = [
    {"id": "trip", "phase": "旅行前", "title": "行程推薦", "solution": "解法 1", "screen": "trip", "now": "2026-11-20T21:00", "location": None},
    {"id": "store", "phase": "旅行前", "title": "AI 選方案", "solution": "解法 1", "screen": "store", "now": "2026-11-20T21:10", "location": None},
    {"id": "support", "phase": "旅行前", "title": "客服", "solution": "解法 1", "screen": "support", "now": "2026-11-20T21:15", "location": None},
    {"id": "spot", "phase": "旅行前", "title": "問經驗", "solution": "解法 2", "screen": "spot", "now": "2026-11-21T22:00", "location": None, "spot": "kiyomizu"},
    {"id": "live", "phase": "旅行中", "title": "現場問答", "solution": "解法 2", "screen": "live", "now": "2026-12-10T14:20", "location": "arashiyama"},
    {"id": "share", "phase": "旅行中", "title": "經驗換流量", "solution": "解法 3", "screen": "share", "now": "2026-12-09T11:00", "location": "usj_nintendo"},
    {"id": "me", "phase": "旅行後", "title": "經驗卡", "solution": "行銷", "screen": "me", "now": "2026-12-13T20:00", "location": None},
]

DEFAULT_STATE = {
    "scene": "trip",
    "now": SCENES[0]["now"],
    "location": None,
    "returning": False,          # 回購者：有上次的實際用量
    "past_daily_gb": 1.6,        # 回購者上次在日本的每日用量
    "has_esim": False,
    "esim": None,                # {"plan_id","name","days","region","price"}
    "app_bound": False,
    "bonus_mb": 0,
    "qa_used": 0,
    "cards": [],                 # 旅後經驗卡
    "shared": [],                # 這個 session 分享過的經驗 id
}

_lock = threading.Lock()
_sessions = {}
_experiences = copy.deepcopy(SEED_EXPERIENCES)


def new_session_id():
    return uuid.uuid4().hex


def get_state(sid):
    with _lock:
        if sid not in _sessions:
            _sessions[sid] = copy.deepcopy(DEFAULT_STATE)
        return _sessions[sid]


def reset_state(sid):
    with _lock:
        # 移除所有 demo 中新分享的經驗（id 以 u 開頭），讓同一段示範可以重來
        _experiences[:] = [e for e in _experiences if not e["id"].startswith("u")]
        _sessions[sid] = copy.deepcopy(DEFAULT_STATE)
        return _sessions[sid]


def apply_scene(state, scene_id):
    scene = next((s for s in SCENES if s["id"] == scene_id), None)
    if not scene:
        return None
    state["scene"] = scene_id
    state["now"] = scene["now"]
    state["location"] = scene["location"]
    return scene


def public_state(state):
    s = dict(state)
    s["qa_quota"] = Config.ESIM_QA_QUOTA if state["has_esim"] else Config.FREE_QA_QUOTA
    s["qa_left"] = max(0, s["qa_quota"] - state["qa_used"])
    s["location_name"] = SPOTS[state["location"]]["name"] if state["location"] else None
    return s


# ---------- 經驗庫 ----------
def experiences():
    return _experiences


def add_experience(exp):
    with _lock:
        _experiences.append(exp)


# ---------- 時間工具 ----------
WEEKDAYS = "一二三四五六日"


def parse_dt(s):
    return datetime.fromisoformat(s)


def time_slot(dt):
    h = dt.hour
    if 5 <= h < 11:
        return "早上"
    if 11 <= h < 14:
        return "中午"
    if 14 <= h < 17:
        return "下午"
    return "晚上"


def day_type(dt):
    return "週末" if dt.weekday() >= 5 else "平日"


def fmt_dt(dt):
    return f"{dt.year}/{dt.month}/{dt.day}（{WEEKDAYS[dt.weekday()]}）{dt:%H:%M}"


def ago_label(dt, now):
    sec = (now - dt).total_seconds()
    if sec < 60:
        return "剛剛"
    if sec < 3600:
        return f"{int(sec // 60)} 分鐘前"
    if sec < 86400:
        return f"{int(sec // 3600)} 小時前"
    days = int(sec // 86400)
    if days < 30:
        return f"{days} 天前"
    if days < 365:
        return f"{days // 30} 個月前"
    return f"{days // 365} 年前"
