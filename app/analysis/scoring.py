"""多因子量化评分引擎：趋势 / 动量 / 波动 / 量能 四因子，0-100 分。

纯函数实现，输入 indicators.compute() 的 summary + 最近行情，
输出总评分、评级、因子明细与文字解读 —— 可离线单元测试。
"""
from __future__ import annotations

from typing import Dict, List, Optional


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def score_trend(ind: Dict, ret: Dict) -> Dict:
    """趋势因子（0-30）：均线系统。"""
    s = 0.0
    notes = []
    ma = ind.get("ma", {})
    price = ind.get("price") or 0
    ma5, ma10, ma20, ma60 = ma.get("ma5"), ma.get("ma10"), ma.get("ma20"), ma.get("ma60")

    if ma20 and price > ma20:
        s += 8; notes.append("价格站上 MA20")
    else:
        notes.append("价格跌破 MA20")
    if ma5 and ma10 and ma20 and ma5 > ma10 > ma20:
        s += 10; notes.append("均线多头排列")
    elif ma5 and ma10 and ma20 and ma5 < ma10 < ma20:
        notes.append("均线空头排列")
    else:
        s += 4; notes.append("均线纠缠")
    if ma60 and price > ma60:
        s += 6; notes.append("中期趋势向上(MA60之上)")
    else:
        notes.append("中期趋势偏弱(MA60之下)")
    if ret.get("ret_20d") is not None:
        s += _clamp(0.5 + ret["ret_20d"] / 0.20) * 6  # ±20% 映射到 0~6
    return {"name": "趋势", "score": round(s), "max": 30, "notes": notes}


def score_momentum(ind: Dict, ret: Dict) -> Dict:
    """动量因子（0-25）：MACD + RSI + 近期涨幅。"""
    s = 0.0
    notes = []
    macd = ind.get("macd", {})
    rsi = ind.get("rsi", {})
    if macd.get("dif") is not None and macd.get("dea") is not None:
        if macd["dif"] > macd["dea"]:
            s += 8; notes.append("MACD DIF 在 DEA 之上")
        else:
            notes.append("MACD DIF 在 DEA 之下")
        if macd.get("above_zero"):
            s += 4; notes.append("MACD 零轴上方(多头市场)")
        else:
            notes.append("MACD 零轴下方(空头市场)")
    if macd.get("gold_cross"):
        s += 3; notes.append("MACD 刚金叉")
    if macd.get("dead_cross"):
        notes.append("MACD 刚死叉")
    r14 = rsi.get("rsi14")
    if r14 is not None:
        if 45 <= r14 <= 65:
            s += 6; notes.append(f"RSI14={r14:.0f} 健康区间")
        elif 65 < r14 <= 75:
            s += 4; notes.append(f"RSI14={r14:.0f} 偏强但接近超买")
        elif r14 > 75:
            s += 2; notes.append(f"RSI14={r14:.0f} 超买，追高风险")
        elif 35 <= r14 < 45:
            s += 4; notes.append(f"RSI14={r14:.0f} 偏弱")
        else:
            notes.append(f"RSI14={r14:.0f} 超卖，关注反弹")
    if ret.get("ret_5d") is not None:
        s += _clamp(0.5 + ret["ret_5d"] / 0.15) * 4
    return {"name": "动量", "score": round(s), "max": 25, "notes": notes}


def score_volatility(ind: Dict) -> Dict:
    """波动因子（0-20）：布林带位置 + ATR 水平。"""
    s = 0.0
    notes = []
    boll = ind.get("boll", {})
    atr = ind.get("atr", {})
    pos = boll.get("pos")
    if pos is not None:
        if 0.35 <= pos <= 0.75:
            s += 10; notes.append("价格处于布林带中轨附近，运行平稳")
        elif 0.75 < pos <= 1.0:
            s += 7; notes.append("价格逼近布林上轨，强势但需防回落")
        elif pos > 1.0:
            s += 4; notes.append("价格突破布林上轨，短期过热")
        elif 0.15 <= pos < 0.35:
            s += 6; notes.append("价格处于布林中下轨之间，偏弱")
        else:
            s += 3; notes.append("价格贴近布林下轨，弱势/超跌")
    pct = atr.get("pct")
    if pct is not None:
        if pct <= 1.5:
            s += 8; notes.append(f"ATR={pct}% 波动低，走势稳健")
        elif pct <= 3:
            s += 6; notes.append(f"ATR={pct}% 波动适中")
        else:
            s += 3; notes.append(f"ATR={pct}% 波动剧烈，注意风控")
    return {"name": "波动", "score": round(s), "max": 20, "notes": notes}


def score_volume(ind: Dict, flow: Optional[Dict]) -> Dict:
    """量能因子（0-25）：量比 + 主力资金。"""
    s = 0.0
    notes = []
    ratio = (ind.get("volume") or {}).get("ratio_ma5")
    if ratio is not None:
        if 1.2 <= ratio <= 2.5:
            s += 10; notes.append(f"量比 {ratio}，温和放量")
        elif ratio > 2.5:
            s += 6; notes.append(f"量比 {ratio}，显著放量，警惕异动")
        elif ratio >= 0.8:
            s += 7; notes.append(f"量比 {ratio}，量能平稳")
        else:
            s += 3; notes.append(f"量比 {ratio}，缩量，观望情绪浓")
    else:
        s += 5
    if flow and flow.get("today_main_net") is not None:
        net = flow["today_main_net"]
        if net > 0:
            s += 10; notes.append(f"今日主力净流入 {net/1e8:.2f} 亿元")
        else:
            notes.append(f"今日主力净流出 {abs(net)/1e8:.2f} 亿元")
        # 近5日累计
        recent = [r["main_net"] for r in flow.get("recent", [])[:5] if r.get("main_net") is not None]
        if recent:
            cum = sum(recent)
            if cum > 0:
                s += 5; notes.append(f"近5日主力累计净流入 {cum/1e8:.2f} 亿元")
            else:
                notes.append(f"近5日主力累计净流出 {abs(cum)/1e8:.2f} 亿元")
    return {"name": "量能资金", "score": round(min(s, 25)), "max": 25, "notes": notes}


RATING_TABLE = [
    (80, "强势", "多因子共振向上，趋势与资金配合良好，可重点跟踪。"),
    (65, "偏多", "整体偏强，可关注回踩均线时的介入机会。"),
    (50, "中性", "多空信号交织，建议观望或轻仓试探。"),
    (35, "偏空", "趋势与资金转弱，反弹注意减仓。"),
    (0, "弱势", "多项因子走弱，规避为上，等待企稳信号。"),
]


def evaluate(ind: Dict, ret: Dict, flow: Optional[Dict] = None) -> Dict:
    """总评分入口。ind: indicators.compute() 结果; ret: {ret_5d, ret_20d, ret_60d}"""
    factors: List[Dict] = [
        score_trend(ind, ret),
        score_momentum(ind, ret),
        score_volatility(ind),
        score_volume(ind, flow),
    ]
    total = sum(f["score"] for f in factors)
    max_total = sum(f["max"] for f in factors)
    normalized = round(total / max_total * 100) if max_total else 50
    for cut, label, desc in RATING_TABLE:
        if normalized >= cut:
            rating, comment = label, desc
            break
    else:  # pragma: no cover
        rating, comment = RATING_TABLE[-1][1], RATING_TABLE[-1][2]
    return {
        "total": normalized,
        "rating": rating,
        "comment": comment,
        "factors": [
            {"name": f["name"], "score": f["score"], "max": f["max"],
             "ratio": round(f["score"] / f["max"], 3), "notes": f["notes"]}
            for f in factors
        ],
    }


def recent_returns(df) -> Dict:
    """近 N 日收益率（df 需含 close 列，升序）。"""
    out: Dict[str, Optional[float]] = {"ret_5d": None, "ret_20d": None, "ret_60d": None}
    try:
        c = df["close"]
        for n, key in ((5, "ret_5d"), (20, "ret_20d"), (60, "ret_60d")):
            if len(c) > n and float(c.iloc[-n - 1]) != 0:
                out[key] = round((float(c.iloc[-1]) / float(c.iloc[-n - 1]) - 1) * 100, 2)
    except Exception:
        pass
    return out
