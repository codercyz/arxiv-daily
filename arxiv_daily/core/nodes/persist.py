"""persist 节点：按日期把本次搜索与论文写入本地 SQLite 历史。"""

from __future__ import annotations

from ...config.settings import Settings
from ...storage.database import Database
from ..state import PipelineState


def persist_node_factory(db: Database, settings: Settings, listener):
    keep = settings.general.history_keep

    def persist_node(state: PipelineState) -> PipelineState:
        papers = state.get("papers") or []
        # 日报链路（skip_history）与关闭历史的搜索不写搜索记录；
        # 但论文本体仍去重入库，否则星标收藏/配图缓存会静默失效
        if state.get("skip_history") or not settings.search.save_history:
            if papers:
                db.upsert_papers(papers)
            return {"search_id": 0}
        search_id = db.save_search(
            state["query"],
            papers,
            llm_used=bool(state.get("enrich_done")),
            meta=state.get("search_meta") or {},
        )
        db.prune_history(keep)
        if listener:
            listener("done", {"search_id": search_id, "papers": papers})
        return {"search_id": search_id}

    return persist_node
