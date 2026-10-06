import json

from services.ai_client import ai, cosine
from services.store import FAQ, PLANS
from services.trace import Trace

TOP_K = 3


def _docs():
    docs = [{"id": f["id"], "title": f["q"], "text": f"{f['q']} {f['tags']} {f['a']}", "answer": f["a"]} for f in FAQ]
    for p in PLANS:
        spec = (f"{p['name']}：每日 {'不限量' if p['unlimited'] else str(p['daily_gb']) + 'GB'}，"
                f"{'支援' if p['hotspot'] else '不支援'}熱點分享，電信 {p['carrier']}，{p['throttle']}。"
                f"價格 " + "、".join(f"{d} 天 NT${v}" for d, v in p["prices"].items()))
        docs.append({"id": p["id"], "title": p["name"], "text": f"{p['name']} 方案 價格 多少錢 費用 規格 {spec}", "answer": spec})
    return docs


DOCS = _docs()


def chat(message, history=None):
    tr = Trace("解法 1｜LLM 客服")
    vecs, emode = ai.embed([message] + [d["text"] for d in DOCS])
    q, dvecs = vecs[0], vecs[1:]
    scored = sorted(((cosine(q, v), d) for v, d in zip(dvecs, DOCS)), key=lambda x: -x[0])[:TOP_K]
    # mock 向量的相似度分布和真的 embedding 不同，門檻分開設
    threshold = 0.35 if emode == "live" else 0.25
    tr.add("1 檢索方案資料庫（RAG）", emode, {
        "問題": message,
        "Top-3": [{"文件": d["title"], "相似度": round(s, 3)} for s, d in scored],
        "門檻": threshold,
    })

    hits = [(s, d) for s, d in scored if s >= threshold]

    def fallback():
        if not hits:
            return {"answer": "這題幫你轉真人客服。", "handoff": True}
        return {"answer": hits[0][1]["answer"], "handoff": False}

    system = (
        "你是去趣 eSIM 客服。只能根據「參考資料」用繁體中文回答，30 字以內。"
        "參考資料無法回答、涉及退款爭議或帳務個資時，handoff 設為 true 並請對方轉真人客服。"
        '輸出 JSON：{"answer": "...", "handoff": false}'
    )
    user = json.dumps({
        "對話紀錄": (history or [])[-6:],
        "問題": message,
        "參考資料": [d["answer"] for _, d in hits] or ["（查無相關資料）"],
    }, ensure_ascii=False)
    out, mode = ai.chat_json(system, user, fallback)
    tr.add("2 回答生成", mode, {"輸出": out})
    if out.get("handoff"):
        tr.add("3 轉真人客服", "rule", {"原因": "檢索不到足夠依據或需要人工處理"})

    return {"answer": out.get("answer", ""), "handoff": bool(out.get("handoff")),
            "sources": [d["title"] for _, d in hits], "trace": tr.to_dict()}
