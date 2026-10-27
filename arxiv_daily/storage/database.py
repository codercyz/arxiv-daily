"""本地历史存储：SQLite（``~/.arxiv_daily/data.db``）。

三张表：
- searches       一次搜索（query、时间、结果数、是否启用 LLM）
- papers         论文（按 arxiv_id 去重，含摘要/关键词/补全信息）
- search_papers  搜索与论文的多对多关联（带展示顺序）
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from ..config.settings import APP_DIR

_SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query        TEXT NOT NULL,
    searched_at  TEXT NOT NULL,
    result_count INTEGER NOT NULL DEFAULT 0,
    llm_used     INTEGER NOT NULL DEFAULT 0,
    meta_json    TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS papers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    arxiv_id         TEXT NOT NULL UNIQUE,
    title            TEXT NOT NULL DEFAULT '',
    url              TEXT NOT NULL DEFAULT '',
    pdf_url          TEXT NOT NULL DEFAULT '',
    published_date   TEXT NOT NULL DEFAULT '',
    one_line_summary TEXT NOT NULL DEFAULT '',
    keywords_json    TEXT NOT NULL DEFAULT '[]',
    passage          TEXT NOT NULL DEFAULT '',
    content          TEXT NOT NULL DEFAULT '',
    authors_json     TEXT NOT NULL DEFAULT '[]',
    full_abstract    TEXT NOT NULL DEFAULT '',
    score            REAL NOT NULL DEFAULT 0,
    enriched         INTEGER NOT NULL DEFAULT 0,
    detail_fetched   INTEGER NOT NULL DEFAULT 0,
    updated_at       TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS search_papers (
    search_id INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    paper_id  INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    rank      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (search_id, paper_id)
);
CREATE INDEX IF NOT EXISTS idx_searches_time ON searches(searched_at DESC);
CREATE TABLE IF NOT EXISTS topics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    query       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    last_run_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS starred (
    arxiv_id   TEXT PRIMARY KEY,
    starred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS digest_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id   INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    day        TEXT NOT NULL,
    paper_id   INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    rank       INTEGER NOT NULL DEFAULT 0,
    pinned     INTEGER NOT NULL DEFAULT 0,
    added_at   TEXT NOT NULL,
    UNIQUE(topic_id, day, paper_id)
);
CREATE TABLE IF NOT EXISTS weekly_reports (
    week_start  TEXT PRIMARY KEY,             -- 周一日期（ISO），同周同键
    content     TEXT NOT NULL,                -- LLM 生成的周报 Markdown
    paper_count INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_cache (
    query      TEXT PRIMARY KEY,
    planned    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_digest_topic_day ON digest_items(topic_id, day);
"""


@dataclass
class PaperRecord:
    arxiv_id: str = ""
    title: str = ""
    url: str = ""
    pdf_url: str = ""
    published_date: str = ""
    one_line_summary: str = ""
    keywords: list[str] = field(default_factory=list)
    passage: str = ""
    content: str = ""
    authors: list[str] = field(default_factory=list)
    full_abstract: str = ""
    abstract_zh: str = ""        # LLM 翻译的中文摘要（持久化，二次查看零成本）
    score: float = 0.0
    enriched: bool = False
    detail_fetched: bool = False
    figures: list = field(default_factory=list)  # [{"caption","url","kind"}]
    repo: list | None = None  # 代码仓库发现结果；None=未搜索 []=搜过无 [..]=候选

    def to_row(self) -> dict:
        row = dict(self.__dict__)
        row["keywords_json"] = json.dumps(self.keywords, ensure_ascii=False)
        row["authors_json"] = json.dumps(self.authors, ensure_ascii=False)
        row["figures_json"] = json.dumps(self.figures, ensure_ascii=False)
        row["repo_json"] = json.dumps(self.repo, ensure_ascii=False) if self.repo is not None else None
        row.pop("keywords")
        row.pop("authors")
        row.pop("figures")
        row.pop("repo")
        row["enriched"] = int(self.enriched)
        row["detail_fetched"] = int(self.detail_fetched)
        row["updated_at"] = datetime.now().isoformat(timespec="seconds")
        return row

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "PaperRecord":
        return cls(
            arxiv_id=row["arxiv_id"],
            title=row["title"],
            url=row["url"],
            pdf_url=row["pdf_url"],
            published_date=row["published_date"],
            one_line_summary=row["one_line_summary"],
            keywords=json.loads(row["keywords_json"] or "[]"),
            passage=row["passage"],
            content=row["content"],
            authors=json.loads(row["authors_json"] or "[]"),
            full_abstract=row["full_abstract"],
            abstract_zh=row["abstract_zh"] or "",
            score=row["score"],
            enriched=bool(row["enriched"]),
            detail_fetched=bool(row["detail_fetched"]),
            figures=json.loads(row["figures_json"] or "[]"),
            repo=(json.loads(row["repo_json"]) if row["repo_json"] is not None else None),
        )


@dataclass
class TopicRecord:
    id: int
    name: str
    query: str
    created_at: str
    last_run_at: str


@dataclass
class SearchRecord:
    id: int
    query: str
    searched_at: str
    result_count: int
    llm_used: bool
    meta_json: str = "{}"


class Database:
    """线程安全（粗粒度锁）的 SQLite 封装。"""

    def __init__(self, db_path: str | Path | None = None):
        self._path = Path(db_path) if db_path else APP_DIR / "data.db"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        # 轻量迁移：老库补 figures_json / abstract_zh 列
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(papers)")}
        if "figures_json" not in columns:
            self._conn.execute(
                "ALTER TABLE papers ADD COLUMN figures_json TEXT NOT NULL DEFAULT '[]'"
            )
            columns.add("figures_json")
        # 轻量迁移：老库补 repo_json 列（代码仓库发现；NULL=未搜索）
        if "repo_json" not in columns:
            self._conn.execute("ALTER TABLE papers ADD COLUMN repo_json TEXT")
        if "abstract_zh" not in columns:
            self._conn.execute(
                "ALTER TABLE papers ADD COLUMN abstract_zh TEXT NOT NULL DEFAULT ''"
            )
        self._conn.commit()

    # ---- 写入 ----
    def save_search(
        self,
        query: str,
        papers: list[PaperRecord],
        *,
        llm_used: bool,
        meta: dict | None = None,
    ) -> int:
        """保存一次搜索及其结果（论文按 arxiv_id upsert），返回 search id。"""
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO searches (query, searched_at, result_count, llm_used, meta_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    query,
                    now,
                    len(papers),
                    int(llm_used),
                    json.dumps(meta or {}, ensure_ascii=False),
                ),
            )
            search_id = int(cur.lastrowid)

            for rank, paper in enumerate(papers):
                row = paper.to_row()
                keys = ",".join(row.keys())
                placeholders = ",".join("?" for _ in row)
                updates = ",".join(
                    f"{k}=excluded.{k}"
                    for k in row
                    if k not in ("arxiv_id", "id")
                )
                self._conn.execute(
                    f"INSERT INTO papers ({keys}) VALUES ({placeholders}) "
                    f"ON CONFLICT(arxiv_id) DO UPDATE SET {updates}",
                    tuple(row.values()),
                )
                paper_row = self._conn.execute(
                    "SELECT id FROM papers WHERE arxiv_id = ?", (paper.arxiv_id,)
                ).fetchone()
                self._conn.execute(
                    "INSERT OR IGNORE INTO search_papers (search_id, paper_id, rank) "
                    "VALUES (?, ?, ?)",
                    (search_id, paper_row["id"], rank),
                )
            self._conn.commit()
        return search_id

    def update_paper(self, paper: PaperRecord) -> None:
        """回写单篇论文的补全/摘要更新。"""
        row = paper.to_row()
        keys = [k for k in row if k != "arxiv_id"]
        sets = ",".join(f"{k}=?" for k in keys)
        with self._lock:
            self._conn.execute(
                f"UPDATE papers SET {sets} WHERE arxiv_id=?",
                (*[row[k] for k in keys], paper.arxiv_id),
            )
            self._conn.commit()

    def delete_search(self, search_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM search_papers WHERE search_id = ?", (search_id,))
            self._conn.execute("DELETE FROM searches WHERE id = ?", (search_id,))
            self._conn.commit()

    def prune_history(self, keep: int) -> None:
        """只保留最近 keep 条搜索记录（keep<=0 不处理）。"""
        if keep <= 0:
            return
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM searches ORDER BY searched_at DESC, id DESC"
            ).fetchall()
            stale = [r["id"] for r in rows[keep:]]
            for sid in stale:
                self._conn.execute(
                    "DELETE FROM search_papers WHERE search_id = ?", (sid,)
                )
                self._conn.execute("DELETE FROM searches WHERE id = ?", (sid,))
            self._conn.commit()

    # ---- 读取 ----
    def list_searches(self, limit: int | None = None) -> list[SearchRecord]:
        sql = "SELECT * FROM searches ORDER BY searched_at DESC, id DESC"
        params: tuple = ()
        if limit:
            sql += " LIMIT ?"
            params = (limit,)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            SearchRecord(
                id=r["id"],
                query=r["query"],
                searched_at=r["searched_at"],
                result_count=r["result_count"],
                llm_used=bool(r["llm_used"]),
                meta_json=r["meta_json"],
            )
            for r in rows
        ]

    def get_papers(self, search_id: int) -> list[PaperRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT p.* FROM papers p JOIN search_papers sp ON sp.paper_id = p.id "
                "WHERE sp.search_id = ? ORDER BY sp.rank",
                (search_id,),
            ).fetchall()
        return [PaperRecord.from_row(r) for r in rows]

    def get_paper(self, arxiv_id: str) -> PaperRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM papers WHERE arxiv_id = ?", (arxiv_id,)
            ).fetchone()
        return PaperRecord.from_row(row) if row else None

    # ---- 主题订阅 ----
    def add_topic(self, name: str, query: str | None = None) -> TopicRecord | None:
        now = datetime.now().isoformat(timespec="seconds")
        name = name.strip()
        if not name:
            return None
        with self._lock:
            try:
                cur = self._conn.execute(
                    "INSERT INTO topics (name, query, created_at) VALUES (?, ?, ?)",
                    (name, (query or name).strip(), now),
                )
            except sqlite3.IntegrityError:
                return None  # 同名主题已存在
            self._conn.commit()
            return TopicRecord(cur.lastrowid, name, (query or name).strip(), now, "")

    def list_topics(self) -> list[TopicRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM topics ORDER BY id"
            ).fetchall()
        return [
            TopicRecord(r["id"], r["name"], r["query"], r["created_at"], r["last_run_at"])
            for r in rows
        ]

    def delete_topic(self, topic_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
            self._conn.commit()

    def touch_topic(self, topic_id: int) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self._conn.execute(
                "UPDATE topics SET last_run_at = ? WHERE id = ?", (now, topic_id)
            )
            self._conn.commit()

    # ---- 收藏 ----
    def star(self, arxiv_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO starred (arxiv_id, starred_at) VALUES (?, ?)",
                (arxiv_id, datetime.now().isoformat(timespec="seconds")),
            )
            self._conn.commit()

    def unstar(self, arxiv_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM starred WHERE arxiv_id = ?", (arxiv_id,))
            self._conn.commit()

    def is_starred(self, arxiv_id: str) -> bool:
        if not arxiv_id:
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM starred WHERE arxiv_id = ?", (arxiv_id,)
            ).fetchone()
        return row is not None

    def list_starred(self) -> list[PaperRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT p.* FROM papers p JOIN starred s ON s.arxiv_id = p.arxiv_id "
                "ORDER BY s.starred_at DESC"
            ).fetchall()
        return [PaperRecord.from_row(r) for r in rows]

    # ---- 订阅收藏夹（日报自动归档：方向 × 日期） ----
    def _upsert_paper(self, paper: PaperRecord) -> int:
        row = paper.to_row()
        keys = ",".join(row.keys())
        placeholders = ",".join("?" for _ in row)
        # repo_json：新值 NULL 时保留旧值——搜索链路反复 upsert 不冲掉已发现的仓库
        updates = ",".join(
            f"{k}=COALESCE(excluded.{k}, papers.{k})" if k == "repo_json"
            else f"{k}=excluded.{k}"
            for k in row if k not in ("arxiv_id", "id")
        )
        self._conn.execute(
            f"INSERT INTO papers ({keys}) VALUES ({placeholders}) "
            f"ON CONFLICT(arxiv_id) DO UPDATE SET {updates}",
            tuple(row.values()),
        )
        found = self._conn.execute(
            "SELECT id FROM papers WHERE arxiv_id = ?", (paper.arxiv_id,)
        ).fetchone()
        return int(found["id"])

    def upsert_papers(self, papers: list[PaperRecord]) -> None:
        """仅入库/更新论文（不产生搜索记录）——供关闭历史或日报链路使用。"""
        with self._lock:
            for paper in papers:
                if paper.arxiv_id:
                    self._upsert_paper(paper)
            self._conn.commit()

    def save_digest_items(self, topic_id: int, day: str, papers: list[PaperRecord]) -> int:
        """把一次日报的结果归档到某方向某天；已存在的跳过，返回新增条数。"""
        now = datetime.now().isoformat(timespec="seconds")
        added = 0
        with self._lock:
            for rank, paper in enumerate(papers):
                if not paper.arxiv_id:
                    continue
                paper_id = self._upsert_paper(paper)
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO digest_items "
                    "(topic_id, day, paper_id, rank, added_at) VALUES (?, ?, ?, ?, ?)",
                    (topic_id, day, paper_id, rank, now),
                )
                added += cur.rowcount or 0
            self._conn.commit()
        return added

    # ---- AI 周报 ----
    def list_weekly_papers(self, topic_id: int, since_day: str) -> list[PaperRecord]:
        """某方向自 since_day 起的日报归档论文，按 arXiv ID 去重、相关度降序。"""
        rows = self._conn.execute(
            "SELECT p.* FROM digest_items d JOIN papers p ON p.id = d.paper_id "
            "WHERE d.topic_id = ? AND d.day >= ? AND p.arxiv_id != '' "
            "GROUP BY p.arxiv_id ORDER BY MAX(p.score) DESC",
            (topic_id, since_day),
        ).fetchall()
        return [PaperRecord.from_row(r) for r in rows]

    def get_weekly_report(self, week_start: str) -> str | None:
        row = self._conn.execute(
            "SELECT content FROM weekly_reports WHERE week_start = ?", (week_start,)
        ).fetchone()
        return row["content"] if row else None

    def save_weekly_report(self, week_start: str, content: str, paper_count: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO weekly_reports (week_start, content, paper_count, created_at) "
                "VALUES (?, ?, ?, ?)",
                (week_start, content, paper_count, datetime.now().isoformat(timespec="seconds")),
            )
            self._conn.commit()

    def list_digest_day(self, topic_id: int, day: str) -> list[PaperRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT p.*, di.pinned AS _pinned FROM digest_items di "
                "JOIN papers p ON p.id = di.paper_id "
                "WHERE di.topic_id = ? AND di.day = ? "
                "ORDER BY di.pinned DESC, p.score DESC, di.rank",
                (topic_id, day),
            ).fetchall()
        papers = [PaperRecord.from_row(r) for r in rows]
        return papers

    def is_digest_pinned(self, topic_id: int, day: str, arxiv_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT di.pinned FROM digest_items di JOIN papers p ON p.id = di.paper_id "
                "WHERE di.topic_id = ? AND di.day = ? AND p.arxiv_id = ?",
                (topic_id, day, arxiv_id),
            ).fetchone()
        return bool(row and row["pinned"])

    def set_digest_pinned(self, topic_id: int, day: str, arxiv_id: str, pinned: bool) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE digest_items SET pinned = ? WHERE topic_id = ? AND day = ? "
                "AND paper_id = (SELECT id FROM papers WHERE arxiv_id = ?)",
                (int(pinned), topic_id, day, arxiv_id),
            )
            self._conn.commit()

    def remove_digest_item(self, topic_id: int, day: str, arxiv_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM digest_items WHERE topic_id = ? AND day = ? "
                "AND paper_id = (SELECT id FROM papers WHERE arxiv_id = ?)",
                (topic_id, day, arxiv_id),
            )
            self._conn.commit()

    def digest_days(self, topic_id: int | None = None) -> list[str]:
        """有归档内容的日期（用于日历高亮）。"""
        sql = "SELECT DISTINCT day FROM digest_items"
        params: tuple = ()
        if topic_id is not None:
            sql += " WHERE topic_id = ?"
            params = (topic_id,)
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY day DESC", params).fetchall()
        return [r["day"] for r in rows]

    # ---- 检索词规划缓存 ----
    def get_cached_plan(self, query: str, ttl_hours: int = 24) -> str | None:
        cutoff = (datetime.now() - timedelta(hours=ttl_hours)).isoformat(timespec="seconds")
        with self._lock:
            row = self._conn.execute(
                "SELECT planned FROM plan_cache WHERE query = ? AND created_at >= ?",
                (query.strip(), cutoff),
            ).fetchone()
        return row["planned"] if row else None

    def set_cached_plan(self, query: str, planned: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO plan_cache (query, planned, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(query) DO UPDATE SET planned = excluded.planned, "
                "created_at = excluded.created_at",
                (query.strip(), planned, datetime.now().isoformat(timespec="seconds")),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
