"""论文 PDF 下载：流式写入，支持进度回调。"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


def _safe_filename(title: str, arxiv_id: str) -> str:
    base = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", title).strip()
    base = re.sub(r"\s+", " ", base)
    if len(base) > 80:
        base = base[:80].rstrip()
    name = f"{base} [{arxiv_id}].pdf" if base else f"{arxiv_id}.pdf"
    return name


def download_pdf(
    url: str,
    *,
    arxiv_id: str,
    title: str,
    dest_dir: str | Path,
    timeout: float = 120.0,
    proxy: str = "",
    progress=None,  # Callable[[done_bytes, total_bytes_or_None], None]
    filename: str | None = None,
    attempts_per_endpoint: int = 3,
) -> Path:
    """下载 PDF：多端点（原链/export 镜像/arxiv 直链）× 断点续传 × 重试。

    国内直连 arxiv.org 的大文件流式下载常被间歇性重置（远程主机强迫关闭连接），
    因此失败时在同一端点续传重试，再逐个切换镜像；全部失败抛 RuntimeError
    （附配置代理的提示）。
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / (filename or _safe_filename(title, arxiv_id))
    if target.exists() and target.stat().st_size > 10240:
        return target

    endpoints = [url]
    if arxiv_id:
        endpoints.append(f"https://export.arxiv.org/pdf/{arxiv_id}")
        endpoints.append(f"https://arxiv.org/pdf/{arxiv_id}")
    endpoints = list(dict.fromkeys(e for e in endpoints if e))

    last_error: Exception | None = None
    for endpoint in endpoints:
        for attempt in range(attempts_per_endpoint):
            pos = target.stat().st_size if target.exists() else 0
            try:
                headers = {"User-Agent": "ArXivDaily/0.1 (open-source paper digest app)"}
                if pos:
                    headers["Range"] = f"bytes={pos}-"
                with httpx.Client(
                    timeout=timeout, proxy=proxy or None, follow_redirects=True
                ) as client:
                    with client.stream("GET", endpoint, headers=headers) as resp:
                        if resp.status_code == 416:  # 已完整
                            return target
                        resp.raise_for_status()
                        append = pos > 0 and resp.status_code == 206
                        total = resp.headers.get("content-range", resp.headers.get("content-length", ""))
                        with open(target, "ab" if append else "wb") as fh:
                            for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                                fh.write(chunk)
                                if progress:
                                    progress(target.stat().st_size, None)
                if target.stat().st_size > 10240:  # 基本 PDF 大小校验
                    return target
                last_error = RuntimeError("下载数据过小，疑似不完整")
            except httpx.HTTPError as exc:
                last_error = exc
                import time

                time.sleep(0.8 + attempt * 0.7)  # 重置多为瞬态，稍候续传
    target.unlink(missing_ok=True)
    raise RuntimeError(
        f"{last_error}。arxiv.org 直连不稳定（常见于国内网络高峰期），"
        "可在「设置 → 网络」配置代理后重试。"
    )
