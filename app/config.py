"""全局配置：从环境变量 / .env 读取。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # 可选依赖，缺失时退回纯环境变量
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover
    pass

ROOT_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT_DIR / ".cache"


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


@dataclass
class Settings:
    # ---- LLM（OpenAI 兼容接口） ----
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "https://api.deepseek.com"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "deepseek-chat"))
    llm_timeout: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT", "120")))
    llm_max_tokens: int = field(default_factory=lambda: int(_env("LLM_MAX_TOKENS", "4096")))

    # ---- 数据缓存 ----
    cache_ttl_quote: int = 300          # 行情快照缓存 5 分钟
    cache_ttl_daily: int = 3600 * 2     # 日线缓存 2 小时
    cache_ttl_news: int = 3600          # 新闻缓存 1 小时

    # ---- 妙想 MCP（东方财富金融数据） ----
    mx_api_key: str = field(default_factory=lambda: _env("EM_API_KEY"))
    mx_base_url: str = field(default_factory=lambda: _env("MX_BASE_URL", "https://mxapi.eastmoney.com/mxds/mcp"))
    mx_timeout: float = field(default_factory=lambda: float(_env("MX_TIMEOUT", "90")))

    # ---- 服务 ----
    host: str = field(default_factory=lambda: _env("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_env("PORT", "8000")))

    @property
    def llm_ready(self) -> bool:
        return bool(self.llm_api_key)


settings = Settings()
CACHE_DIR.mkdir(parents=True, exist_ok=True)
