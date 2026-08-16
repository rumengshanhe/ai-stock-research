"""极简磁盘缓存：pickle 序列化 + TTL 过期，专为 akshare 返回的 DataFrame 设计。"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Callable, Optional

import pickle

from app.config import CACHE_DIR


def _key(namespace: str, *parts: Any) -> Path:
    raw = "|".join(str(p) for p in parts)
    name = hashlib.md5(raw.encode("utf-8")).hexdigest()[:24]
    d = CACHE_DIR / namespace
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{name}.pkl"


def cached(namespace: str, ttl: int, key_fn: Optional[Callable] = None):
    """函数结果缓存装饰器。ttl <= 0 表示不缓存。"""
    def deco(fn: Callable):
        def wrapper(*args, **kwargs):
            if ttl <= 0:
                return fn(*args, **kwargs)
            try:
                key_parts = key_fn(*args, **kwargs) if key_fn else (args, sorted(kwargs.items()))
            except Exception:
                return fn(*args, **kwargs)
            path = _key(namespace, *key_parts)
            if path.exists():
                try:
                    if time.time() - path.stat().st_mtime < ttl:
                        with path.open("rb") as f:
                            return pickle.load(f)
                except Exception:
                    pass
            value = fn(*args, **kwargs)
            if value is None:
                return value
            try:
                with path.open("wb") as f:
                    pickle.dump(value, f)
            except Exception:
                pass
            return value
        wrapper.__name__ = fn.__name__
        return wrapper
    return deco
