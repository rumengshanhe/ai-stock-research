"""妙想（东方财富）MCP 数据客户端。

直连 https://mxapi.eastmoney.com/mxds/mcp（StreamableHttp, 无状态 JSON-RPC），
把妙想的 11 个金融工具接入本项目：资讯/公告检索、A股/港美股/基金/债券/宏观数据、选股器。

统一返回结构（实测）: {"data": [{"columns": [...], "items": [[...]], "sheetName": "..."}]}
未配置 EM_API_KEY 时所有接口优雅降级（MXError），上层回退 AkShare。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.data.cache import cached

# 允许透传给通用调用端的工具白名单（mx_ 前缀校验之外的二次防护）
KNOWN_TOOLS = {
    "mx_stocks_screener", "mx_finance_search_news", "mx_finance_search_notice",
    "mx_ashare_finance_data", "mx_fund_finance_data", "mx_bond_finance_data",
    "mx_index_block_finance_data", "mx_us_finance_data", "mx_hk_finance_data",
    "mx_comprehensive_finance_data", "mx_macro_data",
}


class MXError(RuntimeError):
    pass


def mx_ready() -> bool:
    return bool(settings.mx_api_key)


def _parse_content(result: Dict) -> Any:
    """从 tools/call 结果提取数据：优先 structuredContent，否则解析文本块 JSON。"""
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    for block in result.get("content") or []:
        if block.get("type") == "text":
            text = block.get("text", "")
            try:
                return json.loads(text)
            except Exception:
                return text
    return None


def _call_raw(tool: str, query: str, timeout: Optional[float] = None) -> Any:
    """单次无状态 tools/call。"""
    if not mx_ready():
        raise MXError("未配置 EM_API_KEY（妙想数据不可用）")
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": {"query": query}},
    }
    headers = {
        "em_api_key": settings.mx_api_key,
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout or settings.mx_timeout) as client:
            resp = client.post(settings.mx_base_url, json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise MXError(f"妙想接口请求失败: {e}") from e
    if resp.status_code != 200:
        raise MXError(f"妙想接口返回 {resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
    except Exception as e:
        raise MXError(f"妙想响应解析失败: {e}") from e
    if body.get("error"):
        raise MXError(f"妙想调用错误: {body['error']}")
    result = body.get("result") or {}
    if result.get("isError"):
        texts = [b.get("text", "") for b in (result.get("content") or []) if b.get("type") == "text"]
        raise MXError("妙想工具返回错误: " + " ".join(texts)[:300])
    return _parse_content(result)


def _tables(parsed: Any) -> List[Dict]:
    """归一化为表 dict 列表: [{columns, items, sheetName}]。"""
    if isinstance(parsed, dict) and isinstance(parsed.get("data"), list):
        return [t for t in parsed["data"] if isinstance(t, dict)]
    if isinstance(parsed, dict) and "columns" in parsed:
        return [parsed]
    return []


def _rows_to_records(table: Dict) -> List[Dict]:
    """columns + items(行数组) -> record dict 列表。"""
    cols = table.get("columns") or []
    out = []
    for row in table.get("items") or []:
        if not isinstance(row, list):
            continue
        rec = {}
        for i, c in enumerate(cols):
            rec[str(c)] = row[i] if i < len(row) else None
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# 高层接口
# ---------------------------------------------------------------------------

@cached("mx_news", settings.cache_ttl_news, key_fn=lambda symbol, name, limit=8: (symbol, limit))
def mx_news(symbol: str, name: str, limit: int = 8) -> List[Dict]:
    """个股资讯（妙想语义检索）。返回 [{title, summary, time, source, url}]"""
    query = f"{name}({symbol}) 最新资讯"
    parsed = _call_raw("mx_finance_search_news", query)
    records: List[Dict] = []
    for t in _tables(parsed):
        for r in _rows_to_records(t):
            records.append({
                "title": str(r.get("标题") or "")[:120],
                "summary": str(r.get("摘要") or "")[:200],
                "time": str(r.get("发布时间") or "")[:16],
                "source": str(r.get("来源") or ""),
                "url": str(r.get("跳转链接") or ""),
            })
    # 去重（同标题只留一条）
    seen, uniq = set(), []
    for r in records:
        if r["title"] and r["title"] not in seen:
            seen.add(r["title"])
            uniq.append(r)
    return uniq[:limit]


@cached("mx_notice", settings.cache_ttl_news, key_fn=lambda symbol, name, limit=5: (symbol, limit))
def mx_notices(symbol: str, name: str, limit: int = 5) -> List[Dict]:
    """个股公告（妙想官方披露检索）。"""
    query = f"{name}({symbol}) 最近公告"
    parsed = _call_raw("mx_finance_search_notice", query)
    records: List[Dict] = []
    for t in _tables(parsed):
        for r in _rows_to_records(t):
            records.append({
                "title": str(r.get("标题") or "")[:120],
                "summary": str(r.get("摘要") or "")[:160],
                "time": str(r.get("发布时间") or "")[:16],
                "source": str(r.get("来源") or ""),
                "url": str(r.get("跳转链接") or ""),
            })
    seen, uniq = set(), []
    for r in records:
        if r["title"] and r["title"] not in seen:
            seen.add(r["title"])
            uniq.append(r)
    return uniq[:limit]


@cached("mx_query", 1800, key_fn=lambda query: query)
def mx_query(tool: str, query: str) -> Dict:
    """通用工具调用（白名单校验）。返回 {ok, tool, query, tables}。"""
    if tool not in KNOWN_TOOLS:
        raise MXError(f"未知工具 {tool}，可用: {sorted(KNOWN_TOOLS)}")
    parsed = _call_raw(tool, query)
    tables = _tables(parsed)
    return {
        "ok": True,
        "tool": tool,
        "query": query,
        "tables": [
            {"sheetName": t.get("sheetName", ""), "columns": t.get("columns", []),
             "items": t.get("items", [])}
            for t in tables
        ] if tables else [],
        "raw": None if tables else (parsed if isinstance(parsed, str) else json.dumps(parsed, ensure_ascii=False)[:2000]),
    }


def mx_status() -> Dict:
    return {
        "ready": mx_ready(),
        "base_url": settings.mx_base_url,
        "tools": sorted(KNOWN_TOOLS),
    }
