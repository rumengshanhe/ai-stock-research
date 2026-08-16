"""HF Spaces 入口（Gradio SDK 免费版）。

HF 的 Gradio SDK Space 只是执行 python app.py 并把 7860 端口代理到公网，
端口后面跑什么 HTTP 服务并不受限 —— 这里启动本项目的 FastAPI 应用。
（VPS/Docker 部署仍用 Dockerfile + run.py，两条路径互不影响）
"""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "7860")),
        reload=False,
    )
