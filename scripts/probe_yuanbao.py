"""元宝搜索真实 API 探针：验证连通性并检查返回结构。

用法：.venv/Scripts/python.exe scripts/probe_yuanbao.py [查询词]
不会打印 API Key。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from arxiv_daily.config.settings import load_settings
from arxiv_daily.search.yuanbao import YuanbaoSearchProvider


def main() -> int:
    settings = load_settings()
    key = settings.search.api_key
    print(f"API Key: {key[:6]}…{key[-4:] if len(key) > 10 else ''}（已打码）")
    print(f"Base URL: {settings.search.base_url}")
    if not settings.search.ready:
        print("!! 设置中尚无有效 API Key")
        return 1

    provider = YuanbaoSearchProvider(settings.search, proxy=settings.network.proxy)
    query = sys.argv[1] if len(sys.argv) > 1 else "large language model reasoning"
    print(f"\n== 测试搜索: {query!r} (Cnt=10, Site=arxiv.org, Industry=acad, Freshness=d7) ==")
    try:
        resp = provider.search(query, cnt=10, mode=2, industry="acad", site="arxiv.org", freshness="d7")
    except Exception as exc:
        print(f"!! 搜索失败: code={getattr(exc, 'code', '')} message={exc}")
        return 2

    print(f"版本: {resp.version!r}  RequestId: {resp.request_id!r}  结果数: {len(resp.pages)}")
    for i, page in enumerate(resp.pages[:5]):
        print(f"\n-- [{i}] {page.title[:70]}")
        print(f"   url   : {page.url}")
        print(f"   date  : {page.date!r}  site: {page.site!r}  score: {page.score}")
        print(f"   passage: {page.passage[:100]!r}")
        print(f"   content: {page.content[:80]!r}")

    # 原始字段全览（第一条），确认还有哪些可用字段
    if resp.pages:
        print("\n== 第一条原始字段 ==")
        first_raw = resp.raw.get("Pages", ["{}"])[0]
        try:
            raw = json.loads(first_raw) if isinstance(first_raw, str) else first_raw
            print(json.dumps({k: (str(v)[:60]) for k, v in raw.items()},
                             ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            print("(无法解析)", str(first_raw)[:200])

    # 落盘完整原始响应供排查（不含 Key）
    out = ROOT / "docs" / "probe_response.json"
    out.write_text(json.dumps(resp.raw, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整响应已存: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
