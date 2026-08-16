"""离线单元测试：指标计算与评分引擎（合成数据，不访问网络）。

运行:  python tests/test_analysis.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "vendor")):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

import numpy as np
import pandas as pd

from app.analysis import indicators, scoring

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def make_trend_df(n=150, slope=0.004, seed=1):
    """确定性趋势序列：每步固定涨/跌幅 slope + 微小噪声，保证尾部方向与整体一致。"""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.002, n) + slope
    close = 100 * np.exp(np.cumsum(rets))
    high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    open_ = low + (high - low) * rng.random(n)
    vol = rng.integers(80_000, 120_000, n).astype(float)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"date": dates, "open": open_, "high": high,
                         "low": low, "close": close, "volume": vol})


def make_df(n=120, seed=7, trend=0.001, drift=0.0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(trend, 0.02, n) + drift
    close = 100 * np.exp(np.cumsum(rets))
    high = close * (1 + np.abs(rng.normal(0, 0.008, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.008, n)))
    open_ = low + (high - low) * rng.random(n)
    vol = rng.integers(80_000, 120_000, n).astype(float)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"date": dates, "open": open_, "high": high,
                         "low": low, "close": close, "volume": vol})


def test_indicators():
    print("[ indicators ]")
    df = make_df()
    ind = indicators.compute(df)

    check("price = 最新收盘", abs(ind["price"] - round(float(df["close"].iloc[-1]), 2)) < 1e-9)
    ma20 = df["close"].rolling(20, min_periods=1).mean().iloc[-1]
    check("MA20 数值正确", abs(ind["ma"]["ma20"] - round(float(ma20), 2)) < 0.01,
          f'got {ind["ma"]["ma20"]} want {round(float(ma20),2)}')
    check("RSI 在 0~100", 0 <= ind["rsi"]["rsi14"] <= 100, str(ind["rsi"]))
    check("KDJ J 值有限", np.isfinite(ind["kdj"]["j"]))
    check("BOLL upper>mid>lower",
          ind["boll"]["upper"] > ind["boll"]["mid"] > ind["boll"]["lower"], str(ind["boll"]))
    check("BOLL pos 在 0~1 附近", -0.5 <= ind["boll"]["pos"] <= 1.5, str(ind["boll"]["pos"]))
    check("ATR 为正", ind["atr"]["atr14"] > 0)
    check("量比为正数", (ind["volume"]["ratio_ma5"] or 0) > 0)
    check("MACD 金叉/死叉互斥", not (ind["macd"]["gold_cross"] and ind["macd"]["dead_cross"]))

    # 单边上涨行情：趋势信号应为多
    up = make_trend_df(n=150, slope=0.004, seed=3)
    ind_up = indicators.compute(up)
    check("上涨趋势站上MA20", ind_up["signals"]["ma_bull"] or ind_up["ma"]["ma20"] < ind_up["price"])
    check("上涨趋势RSI>50", ind_up["rsi"]["rsi14"] > 50, str(ind_up["rsi"]))

    # 单边下跌行情
    dn = make_trend_df(n=150, slope=-0.004, seed=5)
    ind_dn = indicators.compute(dn)
    check("下跌趋势RSI<50", ind_dn["rsi"]["rsi14"] < 50, str(ind_dn["rsi"]))
    check("下跌趋势MACD零轴下", ind_dn["macd"]["above_zero"] is False)

    frame = indicators.compute_frame(df)
    check("compute_frame 等长且含列", len(frame) == len(df) and
          {"ma5", "dif", "rsi14", "k"} <= set(frame.columns))
    check("MACD hist = (DIF-DEA)*2",
          np.allclose(frame["macd_hist"], (frame["dif"] - frame["dea"]) * 2, atol=1e-10))

    # 常量序列（边界：std=0, 除零）
    flat = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=30, freq="B"),
        "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1000.0,
    })
    ind_flat = indicators.compute(flat)
    check("常量序列不崩溃", ind_flat.get("price") == 10.0)
    check("常量序列 RSI=50 中性", ind_flat["rsi"]["rsi14"] == 50.0, str(ind_flat["rsi"]))

    # 极短序列
    tiny = make_df(n=3, seed=11)
    check("3行数据可计算", indicators.compute(tiny).get("price") is not None)


def test_scoring():
    print("[ scoring ]")
    up = make_trend_df(n=150, slope=0.005, seed=3)
    ind_up = indicators.compute(up)
    ret_up = scoring.recent_returns(up)
    sc_up = scoring.evaluate(ind_up, ret_up, None)

    dn = make_trend_df(n=150, slope=-0.005, seed=5)
    ind_dn = indicators.compute(dn)
    ret_dn = scoring.recent_returns(dn)
    sc_dn = scoring.evaluate(ind_dn, ret_dn, None)

    check("评分是0~100整数", isinstance(sc_up["total"], int) and 0 <= sc_up["total"] <= 100)
    check("上涨行情评分显著高于下跌", sc_up["total"] > sc_dn["total"] + 15,
          f'up={sc_up["total"]} dn={sc_dn["total"]}')
    check("上涨行情评级偏多", sc_up["rating"] in ("强势", "偏多"), sc_up["rating"])
    check("下跌行情评级偏空", sc_dn["rating"] in ("偏空", "弱势"), sc_dn["rating"])
    check("四因子分数不超上限", all(f["score"] <= f["max"] for f in sc_up["factors"]))
    check("因子notes非空", all(f["notes"] for f in sc_up["factors"]))

    # 资金流加分
    flow = {"today_main_net": 5e7, "recent": [{"date": f"2025-01-0{i}", "main_net": 1e7} for i in range(1, 6)]}
    sc_flow = scoring.evaluate(ind_up, ret_up, flow)
    base = scoring.evaluate(ind_up, ret_up, None)
    check("主力净流入提升量能得分", sc_flow["total"] >= base["total"],
          f'{sc_flow["total"]} vs {base["total"]}')

    # recent_returns 数值方向
    check("上涨序列5日收益为正", (ret_up["ret_5d"] or 0) > 0 or ret_up["ret_20d"] > 0, str(ret_up))
    check("下跌序列20日收益为负", ret_dn["ret_20d"] < 0, str(ret_dn))


def test_llm_offline():
    print("[ llm (offline) ]")
    from app.ai.llm import LLMClient, LLMError
    from app.config import settings
    c = LLMClient(api_key="", base_url="https://example.invalid", model="x")
    check("无key时ready=False", c.ready is False)
    try:
        c.chat([{"role": "user", "content": "hi"}])
        check("无key时抛LLMError", False)
    except LLMError as e:
        check("无key时抛LLMError", "LLM_API_KEY" in str(e))
    check("settings默认base_url", settings.llm_base_url.startswith("http"))


if __name__ == "__main__":
    test_indicators()
    test_scoring()
    test_llm_offline()
    print(f"\n===== RESULT: {PASS} passed, {FAIL} failed =====")
    sys.exit(1 if FAIL else 0)
