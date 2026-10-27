"""本机代理探测：默认代理地址若无人监听则自动回退直连。"""

from __future__ import annotations

import socket
import time
from urllib.parse import urlsplit

_cache: dict[str, tuple[float, bool]] = {}
_CACHE_TTL = 60.0  # 秒


def probe_proxy(proxy_url: str, timeout: float = 1.0) -> bool:
    """探测代理端口是否有服务在监听（结果缓存 60s）。"""
    if not proxy_url:
        return False
    now = time.monotonic()
    cached = _cache.get(proxy_url)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    try:
        parts = urlsplit(proxy_url if "//" in proxy_url else f"http://{proxy_url}")
        host = parts.hostname or "127.0.0.1"
        port = parts.port or (443 if parts.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            ok = True
    except OSError:
        ok = False
    _cache[proxy_url] = (now, ok)
    return ok
