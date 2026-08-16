"""FastAPI 应用入口。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.ai.llm import LLMError, LLMClient
from app.ai.research import build_context, generate_report
from app.analysis import indicators, scoring
from app.analysis.ext import compute_ext
from app.config import settings
from app.data.source import (
    DataError, get_kline, get_stock_info, get_capital_flow,
    get_news, get_index_brief, search, get_code_name,
)
from app.data.mx import MXError, mx_ready, mx_news, mx_notices, mx_query, mx_status, KNOWN_TOOLS

app = FastAPI(title="AI 股票投研助手", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

WEB_DIR = Path(__file__).resolve().parent / "web"
_vendor = WEB_DIR / "vendor"
if _vendor.is_dir():
    app.mount("/vendor", StaticFiles(directory=_vendor), name="vendor")


def _err(e: DataError):
    raise HTTPException(status_code=502, detail=str(e))


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "llm_ready": settings.llm_ready,
        "llm_model": settings.llm_model if settings.llm_ready else None,
        "llm_base_url": settings.llm_base_url,
        "mx_ready": mx_ready(),
    }


# ---------------- 妙想 MCP ----------------

def _symbol_name(symbol: str) -> str:
    """代码 -> 名称（供妙想 query 构造；失败回退代码本身）。"""
    try:
        table = get_code_name()
        row = table[table["symbol"] == symbol]
        if not row.empty:
            return str(row.iloc[0]["name"])
    except Exception:
        pass
    return symbol


@app.get("/api/mx/status")
def api_mx_status():
    return mx_status()


@app.get("/api/mx/news")
def api_mx_news(symbol: str, limit: int = Query(8, ge=1, le=20)):
    name = _symbol_name(symbol)
    try:
        return {"source": "mx", "symbol": symbol, "name": name, "items": mx_news(symbol, name, limit)}
    except MXError as e:
        # 降级：AkShare 新闻
        try:
            items = get_news(symbol, limit)
            return {"source": "akshare", "symbol": symbol, "name": name,
                    "fallback_reason": str(e), "items": items}
        except DataError:
            raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/mx/notices")
def api_mx_notices(symbol: str, limit: int = Query(5, ge=1, le=15)):
    name = _symbol_name(symbol)
    try:
        return {"source": "mx", "symbol": symbol, "name": name, "items": mx_notices(symbol, name, limit)}
    except MXError as e:
        return JSONResponse(status_code=200, content={
            "source": "none", "symbol": symbol, "name": name,
            "fallback_reason": str(e), "items": []})  # 公告无 AkShare 等价源，返回空列表


@app.post("/api/mx/call")
def api_mx_call(body: dict):
    """通用妙想工具调用。body: {"tool": "mx_macro_data", "query": "美联储加息历史"}"""
    tool = str((body or {}).get("tool", "")).strip()
    query = str((body or {}).get("query", "")).strip()
    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")
    if tool not in KNOWN_TOOLS:
        raise HTTPException(status_code=400, detail=f"未知工具，可用: {sorted(KNOWN_TOOLS)}")
    try:
        return mx_query(tool, query)
    except MXError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1), withPrice: bool = False):
    try:
        return {"items": search(q, with_price=withPrice)}
    except DataError as e:
        _err(e)


@app.get("/api/index-brief")
def api_index():
    try:
        return {"items": get_index_brief()}
    except DataError as e:
        return JSONResponse(status_code=502, content={"detail": str(e)})


@app.get("/api/kline")
def api_kline(symbol: str, days: int = Query(120, ge=30, le=500), adjust: str = "qfq"):
    try:
        df = get_kline(symbol, days=days, adjust=adjust)
    except DataError as e:
        _err(e)
    frame = indicators.compute_frame(df)
    rows = []
    for i in range(len(df)):
        r = df.iloc[i]
        rows.append({
            "date": str(r["date"])[:10],
            "open": round(float(r["open"]), 2), "high": round(float(r["high"]), 2),
            "low": round(float(r["low"]), 2), "close": round(float(r["close"]), 2),
            "volume": float(r["volume"]),
            "ma5": _rf(frame["ma5"].iloc[i]), "ma10": _rf(frame["ma10"].iloc[i]),
            "ma20": _rf(frame["ma20"].iloc[i]), "ma60": _rf(frame["ma60"].iloc[i]),
            "dif": _rf(frame["dif"].iloc[i]), "dea": _rf(frame["dea"].iloc[i]),
            "macd": _rf(frame["macd_hist"].iloc[i]), "rsi": _rf(frame["rsi14"].iloc[i]),
        })
    return {"symbol": symbol, "count": len(rows), "items": rows}


def _rf(v):
    try:
        f = float(v)
        return None if f != f else round(f, 3)
    except Exception:
        return None


@app.get("/api/analysis")
def api_analysis(symbol: str):
    """技术指标 + 量化评分 + 资金面（不调 LLM，速度快）。"""
    try:
        kline = get_kline(symbol, days=250)
    except DataError as e:
        _err(e)
    ind = indicators.compute(kline)
    ret = scoring.recent_returns(kline)
    try:
        flow = get_capital_flow(symbol)
    except DataError:
        flow = None
    score = scoring.evaluate(ind, ret, flow)
    try:
        info = get_stock_info(symbol)
    except DataError:
        info = {"symbol": symbol, "name": symbol}
    ext = compute_ext(kline)
    return {"symbol": symbol, "info": info, "indicators": ind,
            "returns": ret, "score": score, "capital_flow": flow, "ext": ext}


@app.post("/api/report")
def api_report(body: dict):
    """LLM 生成投研简报（Markdown）。body: {"symbol": "600519"}"""
    symbol = str((body or {}).get("symbol", "")).strip()
    if not symbol or not symbol.isdigit() or len(symbol) != 6:
        raise HTTPException(status_code=400, detail="请提供 6 位股票代码，例如 600519")
    try:
        return generate_report(symbol)
    except DataError as e:
        _err(e)
    except LLMError as e:
        raise HTTPException(status_code=400, detail=str(e))
