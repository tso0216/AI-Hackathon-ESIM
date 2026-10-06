class Trace:
    """記錄每一步 AI 處理，給前端右側「AI 處理流程」面板顯示。"""

    def __init__(self, title):
        self.title = title
        self.steps = []

    def add(self, name, mode, detail):
        # mode: "rule"（規則/程式）、"live"（真的呼叫 API）、"mock…"（模擬）
        self.steps.append({"name": name, "mode": mode, "detail": detail})

    def to_dict(self):
        return {"title": self.title, "steps": self.steps}
