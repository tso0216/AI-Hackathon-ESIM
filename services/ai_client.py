import hashlib
import json
import logging
import math
import re

from config import Config

log = logging.getLogger(__name__)

MOCK_DIM = 256


class AIClient:
    def __init__(self):
        self._client = None
        self._embed_failed = False
        self._embed_cache = {}
        if Config.OPENAI_API_KEY and Config.AI_MODE != "mock":
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=Config.OPENAI_API_KEY, base_url=Config.OPENAI_BASE_URL)
            except ImportError:
                log.warning("找不到 openai 套件，改用 mock 模式")

    @property
    def live(self):
        return self._client is not None

    @property
    def embed_live(self):
        return self.live and not self._embed_failed

    def status(self):
        return {
            "live": self.live,
            "llm": Config.LLM_MODEL if self.live else "mock",
            "embedding": Config.EMBEDDING_MODEL if self.embed_live else "mock",
            "asr": Config.ASR_MODEL if self.live else "mock",
        }

    # ---------- LLM ----------
    def chat_json(self, system, user, fallback):
        """呼叫 LLM 並解析 JSON。回傳 (dict, mode)。fallback 是產生 mock 結果的函式。"""
        if self.live:
            try:
                resp = self._client.chat.completions.create(
                    model=Config.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                )
                return json.loads(resp.choices[0].message.content), "live"
            except Exception as e:  # noqa: BLE001
                log.exception("LLM 呼叫失敗")
                return fallback(), f"mock（LLM 失敗：{_short(e)}）"
        return fallback(), "mock"

    # ---------- Embedding ----------
    def embed(self, texts):
        """回傳 (list[list[float]], mode)。同一個 process 內只會用同一種向量，避免混用。"""
        if self.embed_live:
            missing = [t for t in texts if ("live", t) not in self._embed_cache]
            try:
                for i in range(0, len(missing), 100):
                    chunk = missing[i : i + 100]
                    resp = self._client.embeddings.create(model=Config.EMBEDDING_MODEL, input=chunk)
                    for t, d in zip(chunk, resp.data):
                        self._embed_cache[("live", t)] = d.embedding
                return [self._embed_cache[("live", t)] for t in texts], "live"
            except Exception as e:  # noqa: BLE001
                log.exception("Embedding 呼叫失敗，之後一律改用 mock 向量")
                self._embed_failed = True
                return [mock_embed(t) for t in texts], f"mock（Embedding 失敗：{_short(e)}）"
        return [mock_embed(t) for t in texts], "mock"

    # ---------- ASR ----------
    def transcribe(self, audio_bytes, filename, fallback):
        """語音轉文字。回傳 (text, mode)。"""
        if self.live and audio_bytes:
            try:
                resp = self._client.audio.transcriptions.create(
                    model=Config.ASR_MODEL,
                    file=(filename, audio_bytes),
                    language="zh",
                    # 提示詞幫助辨識中日夾雜的地名
                    prompt="旅遊現場經驗分享，可能夾雜日文地名，例如：嵐山、清水寺、伏見稲荷、任天堂エリア、USJ。",
                )
                return resp.text, "live"
            except Exception as e:  # noqa: BLE001
                log.exception("ASR 呼叫失敗")
                return fallback(), f"mock（ASR 失敗：{_short(e)}）"
        return fallback(), "mock"


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def mock_embed(text):
    """用字元 unigram + bigram 雜湊成固定維度向量，模擬 embedding 的語意相似度。"""
    vec = [0.0] * MOCK_DIM
    chars = [c for c in re.sub(r"\s+", "", text.lower()) if not re.match(r"[，。、？！,.?!：:「」（）()]", c)]
    grams = chars + [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
    for g in grams:
        h = int(hashlib.md5(g.encode()).hexdigest(), 16)
        vec[h % MOCK_DIM] += 2.0 if len(g) == 2 else 1.0
    n = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / n for v in vec]


def _short(e):
    s = str(e)
    return s[:80] + "…" if len(s) > 80 else s


ai = AIClient()
