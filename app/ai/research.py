"""AI 研报生成：聚合行情/指标/评分/资金/新闻 -> 结构化上下文 -> LLM 输出研报。"""
from __future__ import annotations

import json
from typing import Dict

from app.ai.llm import LLMClient, LLMError
from app.analysis import indicators, scoring
from app.analysis.ext import compute_ext
from app.data.source import get_kline, get_stock_info, get_capital_flow, get_news, DataError
from app.data.mx import MXError, mx_news, mx_notices

SYSTEM_PROMPT = """你是一位严谨专业的证券投资分析师（投研助手）。你将收到一只 A 股股票的结构化数据（行情、技术指标、量化评分、资金流、新闻摘要）。
请基于**只给定的数据**撰写一份中文投研简报，要求：
1. 只引用数据中存在的事实，禁止编造数据；数据未提供的方面不要臆测。
2. 输出 Markdown，结构为：
# {股票名称}({代码}) 投研简报
## 一、核心结论
## 二、技术面分析
## 三、量价与资金面
## 四、舆情与消息面（若无新闻数据则简要说明）
## 五、风险提示
## 六、操作建议
3. 语言专业克制，多用数据支撑；明确区分"事实"与"推断"。
4. 结尾附一行免责声明：本报告由 AI 基于公开数据生成，不构成投资建议。
5. 篇幅 600~1000 字。"""


def build_context(symbol: str) -> Dict:
    """聚合一只股票的全部分析上下文（不含 LLM）。"""
    kline = get_kline(symbol, days=250)
    ind = indicators.compute(kline)
    frame = indicators.compute_frame(kline)
    ret = scoring.recent_returns(kline)
    try:
        flow = get_capital_flow(symbol)
    except DataError:
        flow = None
    score = scoring.evaluate(ind, ret, flow)
    ext = compute_ext(kline)
    try:
        info = get_stock_info(symbol)
    except DataError:
        info = {"symbol": symbol, "name": symbol}
    stock_name = ""
    try:
        stock_name = info.get("name", "") if isinstance(info, dict) else ""
    except Exception:
        pass
    # 资讯：妙想语义检索优先，AkShare 回退
    news: list = []
    try:
        news = mx_news(symbol, stock_name or symbol, limit=8)
        news_source = "mx"
    except MXError:
        try:
            news = get_news(symbol, limit=8)
            news_source = "akshare"
        except DataError:
            news, news_source = [], "none"
    # 公告：仅妙想提供
    try:
        notices = mx_notices(symbol, stock_name or symbol, limit=5)
    except MXError:
        notices = []

    last = kline.iloc[-1]
    return {
        "symbol": symbol,
        "info": info,
        "quote": {
            "date": str(last["date"])[:10],
            "close": round(float(last["close"]), 2),
            "pct_chg": round(float(last.get("pct_chg", 0) or 0), 2),
            "turnover": last.get("turnover"),
        },
        "returns": ret,
        "indicators": ind,
        "ext_indicators": ext,
        "score": score,
        "capital_flow": flow,
        "news": news,
        "news_source": news_source,
        "notices": notices,
        "kline_tail": [
            {
                "date": str(r["date"])[:10],
                "open": round(float(r["open"]), 2), "high": round(float(r["high"]), 2),
                "low": round(float(r["low"]), 2), "close": round(float(r["close"]), 2),
                "volume": float(r["volume"]),
            }
            for _, r in kline.tail(60).iterrows()
        ],
        "ma_tail": [
            {"date": str(kline["date"].iloc[i])[:10],
             "ma5": _r(frame["ma5"].iloc[i]), "ma10": _r(frame["ma10"].iloc[i]),
             "ma20": _r(frame["ma20"].iloc[i]), "ma60": _r(frame["ma60"].iloc[i])}
            for i in range(max(0, len(kline) - 60), len(kline))
        ],
    }


def _r(v):
    try:
        return round(float(v), 2)
    except Exception:
        return None


def generate_report(symbol: str, llm: LLMClient = None) -> Dict:
    """生成 AI 研报：{symbol, name, context_summary, report(markdown)}。"""
    llm = llm or LLMClient()
    ctx = build_context(symbol)
    payload = {
        "股票": {"代码": ctx["symbol"], "名称": ctx["info"].get("name", ""),
                 "行业": ctx["info"].get("industry", ""), "市盈率": ctx["info"].get("pe"),
                 "总市值(亿)": round(ctx["info"]["total_cap"] / 1e8, 1) if ctx["info"].get("total_cap") else None},
        "最新行情": ctx["quote"],
        "区间收益(%)": ctx["returns"],
        "技术指标": ctx["indicators"],
        "扩展指标(pandas-ta)": (ctx.get("ext_indicators") or {}).get("flat") or "数据缺失",
        "量化评分": ctx["score"],
        "资金流": {
            "今日主力净流入(元)": (ctx.get("capital_flow") or {}).get("today_main_net"),
            "近5日": [
                {"date": r["date"], "main_net": r["main_net"]}
                for r in (ctx.get("capital_flow") or {}).get("recent", [])[:5]
            ],
        } if ctx.get("capital_flow") else "数据缺失",
        "近期新闻": [{"时间": n.get("time", ""), "标题": n.get("title", ""),
                     "摘要": n.get("summary", "")[:100]} for n in ctx["news"]] or "暂无",
        "公司公告": [{"时间": n.get("time", ""), "标题": n.get("title", "")}
                    for n in ctx.get("notices", [])] or "暂无",
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "请基于以下数据撰写投研简报：\n\n" + json.dumps(payload, ensure_ascii=False, indent=1)},
    ]
    report = llm.chat(messages, temperature=0.4)
    return {
        "symbol": ctx["symbol"],
        "name": ctx["info"].get("name", ctx["symbol"]),
        "score": ctx["score"]["total"],
        "rating": ctx["score"]["rating"],
        "report": report,
    }
