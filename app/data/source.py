"""AkShare 数据源封装：A股行情、个股资料、资金流、新闻。

所有接口都做了容错：数据源失败时抛 DataError，由 API 层转成友好错误。
列名统一为英文：date/open/high/low/close/volume/amount/...
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from app.config import settings
from app.data.cache import cached

try:
    import akshare as ak
except ImportError as e:  # pragma: no cover
    raise ImportError("缺少依赖 akshare，请先执行: pip install -r requirements.txt") from e


class DataError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def market_of(symbol: str) -> str:
    """根据股票代码推断交易所（东方财富 sh/sz/bj 参数）。"""
    s = str(symbol).strip()
    if s.startswith(("6", "9", "688", "689")):
        return "sh"
    if s.startswith(("8", "4", "92")):
        return "bj"
    return "sz"


def normalize_symbol(symbol: str) -> str:
    s = str(symbol).strip()
    for ch in ("sh", "sz", "bj", ".", "-"):
        s = s.replace(ch, "")
    return s.zfill(6) if s.isdigit() else s


# ---------------------------------------------------------------------------
# 数据接口
# ---------------------------------------------------------------------------

def _kline_em(symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
    """东财日线（可能被 IP 限流）。"""
    df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                            start_date=start, end_date=end, adjust=adjust)
    df = df.rename(columns={
        "日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low",
        "成交量": "volume", "成交额": "amount", "振幅": "amplitude", "涨跌幅": "pct_chg",
        "涨跌额": "chg", "换手率": "turnover",
    })
    return df


def _kline_sina(symbol: str, start: str, end: str, adjust: str) -> pd.DataFrame:
    """新浪日线备源。symbol 需带交易所前缀（sh/sz/bj）。"""
    prefixed = market_of(symbol) + symbol
    df = ak.stock_zh_a_daily(symbol=prefixed, start_date=start, end_date=end, adjust=adjust)
    # 新浪列名 date/open/high/low/close/volume/amount(可能无)/turnover
    if "amount" not in df.columns:
        df["amount"] = float("nan")
    if "turnover" not in df.columns:
        df["turnover"] = float("nan")
    return df


@cached("hist_daily", settings.cache_ttl_daily, key_fn=lambda symbol, days=250, adjust="qfq": (symbol, days, adjust))
def get_kline(symbol: str, days: int = 250, adjust: str = "qfq") -> pd.DataFrame:
    """日 K 线（默认前复权、近 ~1 年）。东财 → 新浪 双源回退。"""
    symbol = normalize_symbol(symbol)
    end = pd.Timestamp.today()
    start = end - pd.Timedelta(days=int(days * 1.6) + 30)
    s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    df, last_err = None, None
    for fn in (_kline_em, _kline_sina):
        try:
            df = fn(symbol, s, e, adjust)
            if df is not None and not df.empty:
                break
        except Exception as ex:
            last_err = ex
            continue
    if df is None or df.empty:
        raise DataError(f"获取 {symbol} 日线失败（东财/新浪均不可用）: {last_err}")

    df["date"] = pd.to_datetime(df["date"])
    keep = [c for c in ["date", "open", "high", "low", "close", "volume", "amount",
                        "pct_chg", "turnover"] if c in df.columns]
    df = df[keep].tail(days).reset_index(drop=True)
    return df


@cached("code_name", 3600 * 24, key_fn=lambda: "all")
def get_code_name() -> pd.DataFrame:
    """全市场代码-名称表（轻量，缓存 24h，搜索主数据源）。"""
    try:
        df = ak.stock_info_a_code_name()
    except Exception as e:
        raise DataError(f"获取代码名称表失败: {e}") from e
    return df.rename(columns={"code": "symbol", "name": "name"})


@cached("spot_sina", settings.cache_ttl_quote)
def get_spot_sina() -> pd.DataFrame:
    """新浪全市场快照（搜索联想里补充实时价格，失败不影响搜索）。"""
    try:
        df = ak.stock_zh_a_spot()
    except Exception as e:
        raise DataError(f"获取市场快照失败: {e}") from e
    return df.rename(columns={"代码": "symbol", "名称": "name", "最新价": "price",
                              "涨跌额": "chg", "涨跌幅": "pct_chg"})


def search(keyword: str, limit: int = 12, with_price: bool = False) -> List[Dict]:
    """按代码或名称搜索股票（主匹配用代码名称表，毫秒级）。

    with_price=True 时尝试新浪快照补实时价格（首次较慢，供需要价格的调用方使用）。
    """
    kw = str(keyword).strip().lower()
    if not kw:
        return []
    try:
        table = get_code_name()
    except DataError:
        table = pd.DataFrame()
    if table is None or table.empty:
        return []
    mask = table["symbol"].astype(str).str.contains(kw, na=False)
    mask = mask | table["name"].astype(str).str.lower().str.contains(kw, na=False)
    hits = table[mask].head(limit)

    price_map: Dict[str, Dict] = {}
    if with_price and not hits.empty:
        try:
            spot = get_spot_sina()
            if spot is not None and not spot.empty:
                sub = spot[spot["symbol"].isin(set(hits["symbol"]))]
                for _, r in sub.iterrows():
                    price_map[str(r["symbol"])] = {
                        "price": _f(r.get("price")), "pct_chg": _f(r.get("pct_chg")),
                    }
        except DataError:
            pass  # 价格补全失败不影响搜索本身

    rows = []
    for _, r in hits.iterrows():
        sym = str(r["symbol"])
        extra = price_map.get(sym, {})
        rows.append({
            "symbol": sym,
            "name": str(r["name"]),
            "price": extra.get("price"),
            "pct_chg": extra.get("pct_chg"),
        })
    return rows


def _f(v) -> Optional[float]:
    try:
        f = float(v)
        return None if pd.isna(f) else round(f, 4)
    except Exception:
        return None


@cached("info", settings.cache_ttl_daily, key_fn=lambda symbol: symbol)
def get_stock_info(symbol: str) -> Dict:
    """个股基础资料：行业、市值、市盈率、上市时间等。"""
    symbol = normalize_symbol(symbol)
    try:
        df = ak.stock_individual_info_em(symbol=symbol)
        info = {str(k): str(v) for k, v in zip(df["item"], df["value"])}
    except Exception as e:
        raise DataError(f"获取 {symbol} 基本资料失败: {e}") from e
    return {
        "symbol": symbol,
        "name": info.get("股票简称", ""),
        "industry": info.get("行业", ""),
        "total_share": _num(info.get("总股本")),
        "float_share": _num(info.get("流通股")),
        "total_cap": _num(info.get("总市值")),
        "float_cap": _num(info.get("流通市值")),
        "pe": _num(info.get("市盈率")),
        "pb": _num(info.get("市净率")),
        "listing_date": info.get("上市时间", ""),
    }


def _num(v) -> Optional[float]:
    try:
        return round(float(str(v).replace(",", "")), 4)
    except Exception:
        return None


@cached("flow", settings.cache_ttl_quote, key_fn=lambda symbol: symbol)
def get_capital_flow(symbol: str) -> Dict:
    """个股近期资金流（主力净流入）。"""
    symbol = normalize_symbol(symbol)
    try:
        df = ak.stock_individual_fund_flow(stock=symbol, market=market_of(symbol))
    except Exception as e:
        raise DataError(f"获取 {symbol} 资金流失败: {e}") from e
    if df is None or df.empty:
        return {"recent": [], "today_main_net": None}
    df = df.rename(columns={
        "日期": "date", "主力净流入-净额": "main_net", "主力净流入-净占比": "main_pct",
        "超大单净流入-净额": "super_net", "大单净流入-净额": "big_net",
        "中单净流入-净额": "mid_net", "小单净流入-净额": "small_net",
    })
    rows = []
    for _, r in df.tail(10).iterrows():
        rows.append({"date": str(r.get("date", "")), "main_net": _num(r.get("main_net"))})
    today = rows[-1]["main_net"] if rows else None
    return {"recent": rows[::-1], "today_main_net": today}


@cached("news", settings.cache_ttl_news, key_fn=lambda symbol: symbol)
def get_news(symbol: str, limit: int = 8) -> List[Dict]:
    """个股相关新闻标题（供 LLM 生成舆情摘要）。"""
    symbol = normalize_symbol(symbol)
    try:
        df = ak.stock_news_em(symbol=symbol)
    except Exception as e:
        raise DataError(f"获取 {symbol} 新闻失败: {e}") from e
    if df is None or df.empty:
        return []
    out = []
    for _, r in df.head(limit).iterrows():
        out.append({
            "title": str(r.get("新闻标题", "")),
            "content": str(r.get("新闻内容", ""))[:200],
            "time": str(r.get("发布时间", ""))[:16],
        })
    return out


@cached("index", settings.cache_ttl_quote)
def get_index_brief() -> List[Dict]:
    """大盘指数概览：上证 / 深成 / 创业板（新浪源，东财指数接口在本机网络下不稳）。"""
    want = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指"}
    try:
        df = ak.stock_zh_index_spot_sina()
    except Exception as e:
        raise DataError(f"获取指数概览失败: {e}") from e
    rows = []
    for _, r in df.iterrows():
        code = str(r.get("代码", "")).lower()
        if code in want:
            rows.append({
                "name": want[code], "symbol": code,
                "price": _f(r.get("最新价")), "pct_chg": _f(r.get("涨跌幅")),
            })
    if not rows:
        raise DataError("指数数据为空")
    return rows


class MarketData:
    """聚合门面，供 service 层调用。"""
    get_kline = staticmethod(get_kline)
    get_code_name = staticmethod(get_code_name)
    get_spot_sina = staticmethod(get_spot_sina)
    search = staticmethod(search)
    get_stock_info = staticmethod(get_stock_info)
    get_capital_flow = staticmethod(get_capital_flow)
    get_news = staticmethod(get_news)
    get_index_brief = staticmethod(get_index_brief)
