"""今日日报服务：主题订阅 → 逐主题执行「今日新增」搜索 → 自动归档到订阅收藏夹。"""

from __future__ import annotations

import copy
from datetime import date, timedelta

from ..config.settings import Settings
from ..core.graph import PipelineDeps, run_pipeline
from ..storage.database import Database, PaperRecord, TopicRecord
from ..workers import build_deps

_RELAX_MESSAGES = [
    "今日没有论文发表，出去放松一下吧~",
    "arXiv 今天没有更新（周末/节假日常态），喝杯咖啡休息一下吧 ☕",
    "今天没有新论文——正好回顾一下收藏夹里的旧文",
    "全网都很安静，研究员也给自己放个假吧 :)",
]


def relax_message(day: str) -> str:
    """按日期稳定选择一条轻松提示（同一天刷新不变）。"""
    index = sum(ord(ch) for ch in day) % len(_RELAX_MESSAGES)
    return _RELAX_MESSAGES[index]


class DigestService:
    """按订阅主题编排今日日报（供后台线程调用）。"""

    def __init__(self, settings: Settings, db: Database):
        self._settings = settings
        self._db = db

    def refresh_topic(
        self,
        topic: TopicRecord,
        *,
        deps_builder=None,
        listener=None,
    ) -> list[PaperRecord]:
        """跑一个主题的日报流水线并自动归档，返回论文列表。

        日报窗口 =「昨天」：arXiv 按工作日美东 02:00 放榜（北京下午），
        "今天"的论文要等北京下午才存在——昨日即最新完整放榜日。
        归档按论文自身日期分桶，历史准确。
        """
        yesterday = date.today() - timedelta(days=1)
        settings = copy.deepcopy(self._settings)
        settings.search.freshness = yesterday.isoformat()

        build = deps_builder or (lambda: build_deps(settings, self._db, listener))
        final = run_pipeline(build(), topic.query, initial={"skip_history": True})
        self._db.touch_topic(topic.id)
        if final.get("error"):
            raise RuntimeError(final["error"])
        papers = final.get("papers") or []
        # 按论文自身日期分桶归档（缺日期归今天）
        by_day: dict[str, list] = {}
        for paper in papers:
            day = paper.published_date[:10] if paper.published_date else yesterday.isoformat()
            if not day.startswith("20"):
                day = yesterday.isoformat()
            by_day.setdefault(day, []).append(paper)
        for day, group in by_day.items():
            self._db.save_digest_items(topic.id, day, group)
        return papers
