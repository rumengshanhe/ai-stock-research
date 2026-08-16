"""扩展指标（基于 pandas-ta，可选依赖）。

提供自研 indicators.py 之外的指标：OBV / CCI / WR(威廉) / MFI / ADX / CMF。
pandas-ta 缺失或部分指标失败时优雅降级（跳过该项），不影响主流程。

与自研实现的约定差异（重要）：
- MACD 柱：国内惯例 (DIF-DEA)*2，pandas-ta 为 (DIF-DEA)，研报使用国内惯例；
- KDJ：pandas-ta 无 KDJ（其 STOCH 为国际随机指标，平滑方式不同）。
"""
from __future__ import annotations

from typing import Dict

try:
    import pandas as pd
    import pandas_ta as ta
    PTA_READY = True
except Exception as _e:  # pragma: no cover
    ta = None
    PTA_READY = False
    _PTA_ERR = str(_e)


def _last(series) -> Dict:
    """返回 {value, change}：最新值与前一日变化方向。"""
    try:
        s = series.dropna()
        if s.empty:
            return {"value": None, "chg": None}
        v = float(s.iloc[-1])
        prev = float(s.iloc[-2]) if len(s) > 1 else None
        chg = None if prev in (None, 0) else round(v - prev, 3)
        return {"value": round(v, 3), "chg": chg}
    except Exception:
        return {"value": None, "chg": None}


def compute_ext(df: pd.DataFrame) -> Dict:
    """计算扩展指标。df 需含 open/high/low/close/volume（升序）。"""
    if not PTA_READY or df is None or df.empty:
        return {"available": PTA_READY,
                "error": None if PTA_READY else _PTA_ERR,
                "indicators": {}}
    out: Dict = {}
    o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]

    def safe(name, fn):
        try:
            r = fn()
            if r is None:
                return
            if isinstance(r, pd.DataFrame):
                for col in r.columns:
                    out[f"{name}_{col}"] = _last(r[col])
            else:
                out[name] = _last(r)
        except Exception:
            pass  # 单指标失败不影响其他

    safe("OBV", lambda: ta.obv(c, v))
    safe("CCI", lambda: ta.cci(h, l, c, length=14))
    safe("WR", lambda: ta.willr(h, l, c, length=14))    # 威廉指标（越低越超买）
    safe("MFI", lambda: ta.mfi(h, l, c, v, length=14))  # 资金流量指标
    safe("ADX", lambda: ta.adx(h, l, c, length=14))     # 趋势强度
    safe("CMF", lambda: ta.cmf(h, l, c, v, length=20))  # Chaikin 资金流

    # 归一化摘要（供前端/LLM 用的扁平视图）
    flat = {}
    for key, val in out.items():
        if val.get("value") is not None:
            flat[key] = val["value"]
    return {"available": True, "error": None, "indicators": out, "flat": flat}
