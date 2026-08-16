"""OpenAI 兼容 LLM 客户端（基于 httpx，适配 DeepSeek / OpenAI / Kimi / 通义等）。"""
from __future__ import annotations

import json
from typing import List, Dict, Optional

import httpx

from app.config import settings


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 model: Optional[str] = None):
        self.api_key = api_key or settings.llm_api_key
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.model = model or settings.llm_model

    @property
    def ready(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: List[Dict], temperature: float = 0.3,
             max_tokens: Optional[int] = None) -> str:
        if not self.ready:
            raise LLMError(
                "未配置 LLM_API_KEY。请在 .env 或环境变量中设置 "
                "LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 后重启服务。"
            )
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or settings.llm_max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=settings.llm_timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as e:
            raise LLMError(f"请求 LLM 接口失败（{self.base_url}）: {e}") from e
        if resp.status_code != 200:
            raise LLMError(f"LLM 接口返回 {resp.status_code}: {resp.text[:500]}")
        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            raise LLMError(f"解析 LLM 响应失败: {e}") from e


client = LLMClient()
