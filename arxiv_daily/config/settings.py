"""应用配置：数据类定义与 JSON 持久化。

配置文件保存在用户主目录 ``~/.arxiv_daily/settings.json``，
与代码完全分离；仓库中不出现任何密钥。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

APP_DIR = Path.home() / ".arxiv_daily"
DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "ArxivDaily"

YUANBAO_DEFAULT_BASE_URL = "https://api.wsa.cloud.tencent.com"


def _coerce(data: dict[str, Any] | None, cls: type) -> dict[str, Any]:
    """把磁盘上的半份配置合并进数据类默认值，忽略未知键。"""
    known = {f.name for f in fields(cls)}
    merged: dict[str, Any] = {
        f.name: cls.__dataclass_fields__[f.name].default for f in fields(cls)
    }
    if data:
        for key, value in data.items():
            if key in known and value is not None:
                merged[key] = value
    return merged


@dataclass
class GeneralSettings:
    start_page: str = "daily"            # 启动页：daily / search
    download_dir: str = str(DEFAULT_DOWNLOAD_DIR)
    history_keep: int = 500              # 历史记录保留条数，0 = 不限制
    open_folder_after_download: bool = True


@dataclass
class SearchSettings:
    provider: str = "yuanbao"
    # 元宝搜索（腾讯云 wsa）
    api_key: str = ""
    base_url: str = YUANBAO_DEFAULT_BASE_URL
    # SearchPro 检索参数
    cnt: int = 20                        # 10/20/30/40/50
    mode: int = 2                        # 0 公开网页 1 权威垂直 2 混合
    industry: str = "acad"               # 垂直信源：acad 学术
    site_filter: str = "arxiv.org"       # 限定站点，留空则全站搜索
    freshness: str = "d7"                # d[N] 近 N 天 / m[N] / y[N] / yyyy-mm-dd
    arxiv_only: bool = True              # 过滤掉非 arxiv.org 的结果
    save_history: bool = True            # 手动搜索是否记入「历史」
    multi_query: bool = True             # 多路检索式召回增强（LLM 规划变体并发检索去重）
    find_repo: bool = True               # 详情页代码仓库发现（元宝 Site=github.com + LLM 精判）
    timeout: int = 30                    # 秒
    max_retries: int = 2

    @property
    def ready(self) -> bool:
        return bool(self.api_key.strip()) and bool(self.base_url.strip())


@dataclass
class LLMSettings:
    enabled: bool = True
    base_url: str = ""                   # OpenAI 兼容接口地址
    api_key: str = ""
    model: str = ""
    use_plan: bool = True                # 检索词规划（中文方向→英文检索式）
    enrich_max_papers: int = 20          # 每次搜索最多为前 N 篇生成 LLM 摘要，0=不限
    temperature: float = 0.3
    max_tokens: int = 1024
    disable_thinking: bool = True         # 关闭思维链（摘要类任务无需思考，显著降延迟）
    summary_language: str = "中文"        # 摘要/关键词输出语言
    timeout: int = 60                    # 秒

    @property
    def ready(self) -> bool:
        return (
            self.enabled
            and bool(self.base_url.strip())
            and bool(self.api_key.strip())
            and bool(self.model.strip())
        )


@dataclass
class NetworkSettings:
    # 默认本机 Clash 系代理端口；无人监听时自动回退直连（proxy_autodetect）
    proxy: str = "http://127.0.0.1:7890"
    proxy_autodetect: bool = True        # 代理不可达时自动回退直连
    use_direct_arxiv: bool = True        # 详情补全/论文配图是否直连 arxiv.org（免费不占配额）

    def live_proxy(self) -> str:
        """实际生效的代理：空=不用；autodetect 且端口无人监听=回退直连。"""
        if not self.proxy.strip():
            return ""
        if self.proxy_autodetect:
            from ..utils.net import probe_proxy

            return self.proxy if probe_proxy(self.proxy) else ""
        return self.proxy


@dataclass
class Settings:
    general: GeneralSettings = field(default_factory=GeneralSettings)
    search: SearchSettings = field(default_factory=SearchSettings)
    llm: LLMSettings = field(default_factory=LLMSettings)
    network: NetworkSettings = field(default_factory=NetworkSettings)

    # ---- 序列化 ----
    def to_dict(self) -> dict[str, Any]:
        return {
            "general": asdict(self.general),
            "search": asdict(self.search),
            "llm": asdict(self.llm),
            "network": asdict(self.network),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        return cls(
            general=GeneralSettings(**_coerce(data.get("general"), GeneralSettings)),
            search=SearchSettings(**_coerce(data.get("search"), SearchSettings)),
            llm=LLMSettings(**_coerce(data.get("llm"), LLMSettings)),
            network=NetworkSettings(**_coerce(data.get("network"), NetworkSettings)),
        )


def settings_path() -> Path:
    return APP_DIR / "settings.json"


def ensure_app_dir() -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DIR


def load_settings(path: Path | None = None) -> Settings:
    path = path or settings_path()
    if not path.exists():
        return Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        settings = Settings.from_dict(data if isinstance(data, dict) else {})
        # 一次性迁移：旧配置的空代理升级为默认本机代理（autodetect 保底，无人监听即直连）
        network_data = (data or {}).get("network") or {}
        if "proxy_autodetect" not in network_data and not settings.network.proxy.strip():
            settings.network.proxy = NetworkSettings().proxy
        return settings
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("配置文件读取失败，使用默认配置: %s", exc)
        return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
