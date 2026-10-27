"""AI 周报：把近 7 天日报归档交给 LLM 写研究者视角的综述。

提示词设计参考了两类开源实践的精髓并重新设计：
- 跨条目归纳机制（合并同主题 / 30 秒总览段 / 数量上限 / 编号原样回填防幻觉）
- 模板变量与输出约束分离（材料结构化、硬性约束显式列出）
反"论文清单"是第一设计目标：判断优先于复述、聚类优先于罗列。
"""

from __future__ import annotations

from datetime import date, timedelta

from ..llm.client import LLMClient
from ..storage.database import Database

MIN_PAPERS = 8          # 样本过少不出综述（宁缺毋滥，不硬凑）
MAX_PAPERS = 40         # 材料截断上限（token 成本控制）
DAYS = 7

SYSTEM_PROMPT = """你是一位资深 AI 研究者，为订阅了特定研究方向的研究生撰写每周文献综述。

读者画像：聪明但时间有限的研究生。他们要的不是论文清单——清单自己会翻——而是你作为前辈的判断：这周什么值得深读、方向正在往哪走。

写作原则（按优先级）：
1. 判断优先于复述：明确指出本周最有创新性的工作，说清"新"在哪——新范式、新问题、反直觉的发现、还是显著的性能跃迁；平庸的工作一笔带过甚至不提。宁可少而准，不可全而浅。
2. 聚类优先于罗列：把论文聚成 2~4 条探索的细分方向，讲清每条方向在解决什么问题、代表工作是谁、你观察到什么趋势（共识 / 分歧 / 升温 / 降温）。
3. 只依据给定材料：评价必须能从标题、摘要、关键词中找到依据，不编造论文内容；材料不足以支撑判断时直说"样本有限，判断置信度一般"。
4. 语言：中文，专业但不端着；术语保留英文原文（如 RAG、agent、reward model）。"""

_TOPICS_BLOCK = """时间范围：{date_range}（共 {count} 篇，按相关度降序排列，编号即引用编号）。
{blocks}"""

_TOPIC_HEADER = """#### 方向：{name}"""

_TASK_TEMPLATE = """## 本周材料
{material}

## 任务
基于以上材料撰写本周综述，Markdown 格式，结构如下：

### 本周看点
2~4 句总述。让读者 30 秒内知道整体节奏：平淡还是热闹？大家在集中攻什么？多方向时点出方向间的关联或反差。

{sections}

### 一句话展望
给读者一个下周值得留意的具体信号（正在形成的共识、新基准、可以跟进的空档……）。

## 硬性约束
- 禁止逐篇罗列摘要、禁止输出论文表格——提到任何工作时必须融入判断（为什么值得读 / 代表什么趋势），孤立复述一律不合格。
- 只能引用材料中编号对应的工作，引用时在标题后标注编号（如 [3]），编号必须与材料一致，不得虚构。
- "值得深读"每个方向最多 3 篇；没有过硬的工作就明说"本周没有突出的工作"并给出理由，不要硬凑。
- 细分方向按论文实际聚类命名，不要用"方法改进类 / 实验类"这种空壳分类名。
- 全文 400~800 字。"""

_SECTION_TEMPLATE = """### 值得深读 · {topic}
0~3 篇。每篇格式：**标题** [编号] —— 2~3 句"为什么值得关注"，讲创新点，不复述摘要。

### 细分方向 · {topic}
2~4 条。每条先用一句话给方向命名，再 2~4 句展开：在解决什么问题 / 代表工作（标注编号）/ 你的观察。"""


class WeeklyError(RuntimeError):
    """周报生成失败（材料不足 / LLM 不可用）。"""


def week_start(today: date | None = None) -> str:
    """本周周一的 ISO 日期（周报缓存键）。"""
    d = today or date.today()
    return (d - timedelta(days=d.weekday())).isoformat()


def build_material(db: Database) -> tuple[int, str]:
    """组装近 7 天各订阅方向的归档材料。返回 (总篇数, 材料文本)。"""
    since = (date.today() - timedelta(days=DAYS - 1)).isoformat()
    blocks: list[str] = []
    total = 0
    index = 0
    for topic in db.list_topics():
        papers = db.list_weekly_papers(topic.id, since)
        if not papers:
            continue
        kept, seen_ids = [], set()
        for p in papers:  # 主题间也可能收录同一篇，全局编号去重
            if p.arxiv_id in seen_ids:
                continue
            seen_ids.add(p.arxiv_id)
            kept.append(p)
        lines = [_TOPIC_HEADER.format(name=topic.name)]
        for p in kept:
            if total >= MAX_PAPERS:
                break
            index += 1
            total += 1
            summary = (p.one_line_summary or p.passage or "")[:80]
            keywords = "、".join((p.keywords or [])[:5])
            lines.append(f"[{index}] {p.title} | {summary} | 关键词：{keywords}")
        blocks.append("\n".join(lines))
        if total >= MAX_PAPERS:
            break
    date_range = f"{since} ~ {date.today().isoformat()}"
    material = _TOPICS_BLOCK.format(
        date_range=date_range, count=total,
        blocks="\n\n".join(blocks) if blocks else "（近 7 天无归档）",
    )
    return total, material


def generate_weekly(db: Database, client: LLMClient | None, *, force: bool = False) -> str:
    """生成（或读缓存）本周综述。材料不足或 LLM 未配置抛 :class:`WeeklyError`。"""
    ws = week_start()
    if not force:
        cached = db.get_weekly_report(ws)
        if cached:
            return cached
    total, material = build_material(db)
    if total < MIN_PAPERS:
        raise WeeklyError(
            f"近 7 天日报归档仅 {total} 篇（至少 {MIN_PAPERS} 篇）。"
            "周报靠积累——每天点一次「刷新昨日日报」，攒几天再来。"
        )
    if client is None or not getattr(client, "configured", False):
        raise WeeklyError("未配置 LLM，无法生成周报（可在「设置 → LLM 增强」配置）")
    topics = [t.name for t in db.list_topics() if db.list_weekly_papers(t.id, (date.today() - timedelta(days=DAYS - 1)).isoformat())]
    sections = "\n\n".join(_SECTION_TEMPLATE.format(topic=t) for t in topics)
    user = _TASK_TEMPLATE.format(material=material, sections=sections)
    content = client.chat(SYSTEM_PROMPT, user, temperature=0.4, max_tokens=2400)
    content = (content or "").strip()
    if len(content) < 200:
        raise WeeklyError("周报生成结果异常（过短），请重试")
    db.save_weekly_report(ws, content, total)
    return content
