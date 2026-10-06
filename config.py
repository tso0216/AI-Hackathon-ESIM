import os

from dotenv import load_dotenv

load_dotenv()

# .env 裡留空的 OPENAI_BASE_URL= 會被 OpenAI SDK 當成空網址，留空時直接移除
if not os.getenv("OPENAI_BASE_URL", "").strip():
    os.environ.pop("OPENAI_BASE_URL", None)


class Config:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip() or None
    AI_MODE = os.getenv("AI_MODE", "auto").strip().lower()

    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-6-luna")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    ASR_MODEL = os.getenv("ASR_MODEL", "whisper-1")

    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret")
    PORT = int(os.getenv("PORT", "5050"))

    # 業務參數
    FREE_QA_QUOTA = 3        # 非 eSIM 用戶的經驗問答次數
    ESIM_QA_QUOTA = 30       # eSIM 用戶專屬額度
    SHARE_REWARD_MB = 500    # 每則通過審核的經驗加碼流量
