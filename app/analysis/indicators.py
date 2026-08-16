"""技术指标计算（纯 pandas 实现，无 TA-Lib 依赖）。

输入 DataFrame 需包含列: date, open, high, low, close, volume
输出指标字典 + 逐行指标 DataFrame（供前端画副图）。
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

REQUIRED = {"open", "high", "low", "close", "volume"}


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=1).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return _sma(s, n)


def ema(s: pd.Series, n: int) -> pd.Series:
    return _ema(s, n)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    dif = _ema(close, fast) - _ema(close, slow)
    dea = _ema(dif, signal)
    hist = (dif - dea) * 2
    return dif, dea, hist


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder 平滑 RSI。"""
    diff = close.diff()
    up = diff.clip(lower=0.0)
    down = (-diff).clip(lower=0.0)
    avg_up = up.ewm(alpha=1.0 / n, adjust=False).mean()
    avg_down = down.ewm(alpha=1.0 / n, adjust=False).mean()
    rs = avg_up / avg_down.replace(0.0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(50.0)


def kdj(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3):
    low_n = df["low"].rolling(n, min_periods=1).min()
    high_n = df["high"].rolling(n, min_periods=1).max()
    rsv = (df["close"] - low_n) / (high_n - low_n).replace(0.0, np.nan) * 100
    rsv = rsv.fillna(50.0)
    k = rsv.ewm(alpha=1.0 / m1, adjust=False).mean()
    d = k.ewm(alpha=1.0 / m2, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def boll(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = _sma(close, n)
    std = close.rolling(n, min_periods=1).std(ddof=0)
    upper = mid + k * std
    lower = mid - k * std
    return upper, mid, lower


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def compute(df: pd.DataFrame) -> Dict:
    """计算全部指标，返回 summary dict。df 需按时间升序。"""
    if df is None or df.empty:
        return {}
    missing = REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"K线数据缺少列: {missing}")

    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]

    ma5, ma10, ma20, ma60 = (_sma(close, n) for n in (5, 10, 20, 60))
    dif, dea, hist = macd(close)
    rsi6, rsi14 = rsi(close, 6), rsi(close, 14)
    k, d, j = kdj(df)
    b_upper, b_mid, b_lower = boll(close)
    atr14 = atr(df)
    vol_ma5 = _sma(vol, 5)

    last_i = len(df) - 1
    price = float(close.iloc[last_i])

    def _v(s: pd.Series, nd: int = 2):
        try:
            f = float(s.iloc[last_i])
            return None if np.isnan(f) else round(f, nd)
        except Exception:
            return None

    # 信号判断
    def _num(v):
        return float(v) if v is not None else None

    n_ma5, n_ma10, n_ma20, n_ma60 = _num(_v(ma5)), _num(_v(ma10)), _num(_v(ma20)), _num(_v(ma60))
    ma_bull = (
        n_ma20 is not None and price > n_ma20
        and n_ma5 is not None and n_ma10 is not None
        and n_ma5 > n_ma10 > n_ma20
    )
    macd_gold = (float(dif.iloc[last_i]) > float(dea.iloc[last_i])) and \
                (float(dif.iloc[last_i - 1]) <= float(dea.iloc[last_i - 1]) if last_i >= 1 else False)
    macd_dead = (float(dif.iloc[last_i]) < float(dea.iloc[last_i])) and \
                (float(dif.iloc[last_i - 1]) >= float(dea.iloc[last_i - 1]) if last_i >= 1 else False)
    b_pos = None
    if b_upper.iloc[last_i] and b_lower.iloc[last_i] and float(b_upper.iloc[last_i]) != float(b_lower.iloc[last_i]):
        b_pos = (price - float(b_lower.iloc[last_i])) / (float(b_upper.iloc[last_i]) - float(b_lower.iloc[last_i]))
    vol_ratio = float(vol.iloc[last_i]) / float(vol_ma5.iloc[last_i - 1]) if last_i >= 1 and float(vol_ma5.iloc[last_i - 1]) > 0 else None

    return {
        "price": round(price, 2),
        "ma": {"ma5": _v(ma5), "ma10": _v(ma10), "ma20": _v(ma20), "ma60": _v(ma60), "bull_alignment": bool(ma_bull)},
        "macd": {
            "dif": _v(dif, 3), "dea": _v(dea, 3), "hist": _v(hist, 3),
            "gold_cross": bool(macd_gold), "dead_cross": bool(macd_dead),
            "above_zero": bool((dif.iloc[last_i] or 0) > 0),
        },
        "rsi": {"rsi6": _v(rsi6), "rsi14": _v(rsi14)},
        "kdj": {"k": _v(k), "d": _v(d), "j": _v(j)},
        "boll": {"upper": _v(b_upper), "mid": _v(b_mid), "lower": _v(b_lower),
                 "pos": round(b_pos, 4) if b_pos is not None else None},
        "atr": {"atr14": _v(atr14, 3),
                "pct": round(float(atr14.iloc[last_i]) / price * 100, 2)},
        "volume": {"ratio_ma5": round(vol_ratio, 2) if vol_ratio is not None else None},
        "signals": {
            "ma_bull": bool(ma_bull),
            "macd_gold": bool(macd_gold),
            "macd_dead": bool(macd_dead),
            "rsi_overbought": bool(rsi14.iloc[last_i] > 70),
            "rsi_oversold": bool(rsi14.iloc[last_i] < 30),
            "boll_above_upper": bool(price > float(b_upper.iloc[last_i])),
            "boll_below_lower": bool(price < float(b_lower.iloc[last_i])),
        },
    }


def compute_frame(df: pd.DataFrame) -> pd.DataFrame:
    """逐行指标（供前端绘制副图），返回与 df 等长的新 DataFrame。"""
    out = pd.DataFrame(index=df.index)
    close = df["close"]
    out["ma5"] = _sma(close, 5)
    out["ma10"] = _sma(close, 10)
    out["ma20"] = _sma(close, 20)
    out["ma60"] = _sma(close, 60)
    dif, dea, hist = macd(close)
    out["dif"], out["dea"], out["macd_hist"] = dif, dea, hist
    out["rsi14"] = rsi(close, 14)
    k, d, j = kdj(df)
    out["k"], out["d"], out["j"] = k, d, j
    return out
