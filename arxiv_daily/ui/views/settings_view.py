"""设置页：左侧分类侧边栏 + 右侧表单（参照 ZCode 的配置流程）。

任何修改即时保存到 ``~/./arxiv_daily/settings.json``，
并通过 :attr:`settingsChanged` 通知主窗口重建搜索/LLM 客户端。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ... import __version__
from ...config.settings import Settings, save_settings
from ...llm.client import LLMClient
from ...search.yuanbao import YuanbaoSearchProvider
from ...workers import FuncWorker
from ..transitions import fade_in
from ..components.nav_rail import NavRail

_MODE_OPTIONS = [("公开网页", 0), ("权威垂直信源", 1), ("混合", 2)]
_INDUSTRY_OPTIONS = [
    ("学术（acad）", "acad"),
    ("新闻（news）", "news"),
    ("政府（gov）", "gov"),
    ("金融（finance）", "finance"),
    ("不限", ""),
]


class SettingsView(QWidget):
    settingsChanged = Signal()

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._worker: FuncWorker | None = None
        self._setup_ui()

    # ---------- 布局骨架 ----------
    def _setup_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 22, 20, 20)

        # 嵌套外壳：白壳圆角矩形，内含分类侧栏 + 表单区
        shell = QFrame()
        shell.setObjectName("settingsShell")
        root.addWidget(shell)
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(10, 16, 14, 16)
        shell_layout.setSpacing(0)

        nav_col = QVBoxLayout()
        nav_col.setContentsMargins(10, 4, 10, 4)
        self.nav = NavRail(["通用", "联网搜索", "LLM 增强", "网络", "关于"])
        self.nav.setFixedWidth(150)
        self.nav.currentChanged.connect(self._on_nav)
        nav_col.addWidget(self.nav)
        nav_col.addStretch(1)
        shell_layout.addLayout(nav_col)

        separator = QFrame()
        separator.setObjectName("settingsSeparator")
        separator.setFixedWidth(1)
        shell_layout.addSpacing(14)
        shell_layout.addWidget(separator)
        shell_layout.addSpacing(6)

        center = QHBoxLayout()
        center.addStretch(1)
        stack_holder = QWidget()
        stack_holder.setMaximumWidth(880)
        stack_layout = QHBoxLayout(stack_holder)
        stack_layout.setContentsMargins(8, 0, 8, 0)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._wrap(self._build_general()))
        self.stack.addWidget(self._wrap(self._build_search()))
        self.stack.addWidget(self._wrap(self._build_llm()))
        self.stack.addWidget(self._wrap(self._build_network()))
        self.stack.addWidget(self._wrap(self._build_about()))
        stack_layout.addWidget(self.stack)
        center.addWidget(stack_holder, 100)
        center.addStretch(1)
        shell_layout.addLayout(center, 1)

        self.nav.setCurrentIndex(0)

    def _wrap(self, inner: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)
        return scroll

    def _page(self, title: str, desc: str = "") -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 30, 20, 26)
        layout.setSpacing(14)
        heading = QLabel(title)
        heading.setObjectName("settingsSectionTitle")
        layout.addWidget(heading)
        if desc:
            note = QLabel(desc)
            note.setObjectName("settingsSectionDesc")
            note.setWordWrap(True)
            layout.addWidget(note)
        layout.addSpacing(6)

        # 右上角「已保存」提示（每个分类页各一份，闪烁时逐个触发）
        self._toasts: list[QLabel] = []
        toast = QLabel("✓ 已保存")
        toast.setObjectName("testResultOk")
        toast.hide()
        self._toasts.append(toast)
        toast_row = QHBoxLayout()
        toast_row.addStretch(1)
        toast_row.addWidget(toast)
        layout.addLayout(toast_row)
        return page, layout

    def _group(self, parent_layout: QVBoxLayout, title: str) -> QVBoxLayout:
        box = QFrame()
        box.setObjectName("settingsGroup")
        inner = QVBoxLayout(box)
        inner.setContentsMargins(20, 16, 20, 16)
        inner.setSpacing(10)
        label = QLabel(title)
        label.setObjectName("groupTitle")
        inner.addWidget(label)
        parent_layout.addWidget(box)
        return inner

    def _row(self, parent_layout: QVBoxLayout, label_text: str, *widgets, stretch_last=True):
        row = QHBoxLayout()
        row.setSpacing(10)
        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        label.setFixedWidth(120)
        row.addWidget(label)
        if len(widgets) == 1:
            row.addWidget(widgets[0], 1)
        else:
            for i, w in enumerate(widgets):
                row.addWidget(w, 1 if (stretch_last and i == len(widgets) - 1) else 0)
        parent_layout.addLayout(row)
        return row

    def _hint(self, parent_layout: QVBoxLayout, text: str):
        hint = QLabel(text)
        hint.setObjectName("settingsSectionDesc")
        hint.setWordWrap(True)
        parent_layout.addWidget(hint)

    # ---------- 通用 ----------
    def _build_general(self) -> QWidget:
        g = self.settings.general
        page, layout = self._page("通用", "应用基础偏好设置")
        group = self._group(layout, "下载与历史")

        self.download_dir_edit = QLineEdit(g.download_dir)
        browse = QPushButton("浏览…")
        browse.setObjectName("secondaryButton")
        browse.clicked.connect(self._pick_download_dir)
        self._row(group, "下载目录", self.download_dir_edit, browse, stretch_last=False)
        self.download_dir_edit.textChanged.connect(
            lambda v: self._set("general", "download_dir", v)
        )

        self.start_page_combo = QComboBox()
        self.start_page_combo.addItem("昨日日报", "daily")
        self.start_page_combo.addItem("论文搜索", "search")
        self._select_data(self.start_page_combo, g.start_page, 0)
        self.start_page_combo.currentIndexChanged.connect(
            lambda i: self._set("general", "start_page", self.start_page_combo.itemData(i))
        )
        self._row(group, "启动页", self.start_page_combo, stretch_last=False)

        self.history_keep_spin = QSpinBox()
        self.history_keep_spin.setRange(0, 100000)
        self.history_keep_spin.setSpecialValueText("不限制")
        self.history_keep_spin.setValue(g.history_keep)
        self.history_keep_spin.valueChanged.connect(
            lambda v: self._set("general", "history_keep", v)
        )
        self._row(group, "历史保留条数", self.history_keep_spin)
        self._hint(group, "仅保留最近 N 条搜索历史（论文记录去重保留）；0 表示不限制。")

        self.open_folder_check = QCheckBox("下载完成后自动打开所在文件夹")
        self.open_folder_check.setChecked(g.open_folder_after_download)
        self.open_folder_check.toggled.connect(
            lambda v: self._set("general", "open_folder_after_download", v)
        )
        self._row(group, "", self.open_folder_check)

        layout.addStretch(1)
        return page

    # ---------- 联网搜索 ----------
    def _build_search(self) -> QWidget:
        s = self.settings.search
        page, layout = self._page(
            "联网搜索",
            "论文发现的唯一数据来源（内置联网搜索服务）。",
        )

        cred = self._group(layout, "凭据")
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("联网搜索服务（内置）", "yuanbao")
        self.provider_combo.currentIndexChanged.connect(
            lambda i: self._set("search", "provider", self.provider_combo.itemData(i))
        )
        self._row(cred, "服务商", self.provider_combo)

        self.search_key_edit = self._key_field(cred, "search", "api_key", s.api_key)

        self.base_url_edit = QLineEdit(s.base_url)
        self.base_url_edit.setPlaceholderText("https://api.wsa.cloud.tencent.com")
        self.base_url_edit.textChanged.connect(lambda v: self._set("search", "base_url", v))
        self._row(cred, "接口地址", self.base_url_edit)
        self._hint(
            cred,
            "API Key 获取步骤见「关于」页。",
        )

        test_row = QHBoxLayout()
        self.search_test_btn = QPushButton("测试连接")
        self.search_test_btn.setObjectName("primaryButton")
        self.search_test_btn.setCursor(Qt.PointingHandCursor)
        self.search_test_btn.clicked.connect(self._test_search)
        self.search_test_result = QLabel("")
        self.search_test_result.setObjectName("hintLabel")
        self.search_test_result.setWordWrap(True)
        test_row.addWidget(self.search_test_btn)
        test_row.addWidget(self.search_test_result, 1)
        cred.addLayout(test_row)

        params = self._group(layout, "检索参数")
        self.cnt_combo = QComboBox()
        for n in (10, 20, 30, 40, 50):
            self.cnt_combo.addItem(str(n), n)
        self._select_data(self.cnt_combo, s.cnt, 1)
        self.cnt_combo.currentIndexChanged.connect(
            lambda i: self._set("search", "cnt", self.cnt_combo.itemData(i))
        )
        self._row(params, "返回条数", self.cnt_combo, stretch_last=False)

        self.mode_combo = QComboBox()
        for text, value in _MODE_OPTIONS:
            self.mode_combo.addItem(text, value)
        self._select_data(self.mode_combo, s.mode, 1)
        self.mode_combo.currentIndexChanged.connect(
            lambda i: self._set("search", "mode", self.mode_combo.itemData(i))
        )
        self._row(params, "搜索模式", self.mode_combo, stretch_last=False)

        self.industry_combo = QComboBox()
        for text, value in _INDUSTRY_OPTIONS:
            self.industry_combo.addItem(text, value)
        self._select_data(self.industry_combo, s.industry, 1)
        self.industry_combo.currentIndexChanged.connect(
            lambda i: self._set("search", "industry", self.industry_combo.itemData(i))
        )
        self._row(params, "垂直信源", self.industry_combo, stretch_last=False)

        self.site_edit = QLineEdit(s.site_filter)
        self.site_edit.setPlaceholderText("arxiv.org，留空则搜索全站")
        self.site_edit.textChanged.connect(lambda v: self._set("search", "site_filter", v))
        self._row(params, "限定站点", self.site_edit)

        self.arxiv_only_check = QCheckBox("仅保留 arXiv 论文结果（过滤新闻/博客等）")
        self.arxiv_only_check.setChecked(s.arxiv_only)
        self.arxiv_only_check.toggled.connect(lambda v: self._set("search", "arxiv_only", v))
        self._row(params, "", self.arxiv_only_check)

        self.multi_query_check = QCheckBox("多路检索式召回增强（LLM 规划同义变体，并发多路检索后去重合并，召回显著提升）")
        self.multi_query_check.setChecked(s.multi_query)
        self.multi_query_check.toggled.connect(lambda v: self._set("search", "multi_query", v))
        self._row(params, "", self.multi_query_check)

        self.find_repo_check = QCheckBox("详情页代码仓库发现（搜索 GitHub 定位论文官方实现）")
        self.find_repo_check.setChecked(getattr(s, "find_repo", True))
        self.find_repo_check.toggled.connect(lambda v: self._set("search", "find_repo", v))
        self._row(params, "", self.find_repo_check)

        self.save_history_check = QCheckBox("手动搜索记入「历史」记录")
        self.save_history_check.setChecked(s.save_history)
        self.save_history_check.toggled.connect(lambda v: self._set("search", "save_history", v))
        self._row(params, "", self.save_history_check)

        adv = self._group(layout, "稳定性")
        self.search_timeout_spin = QSpinBox()
        self.search_timeout_spin.setRange(5, 300)
        self.search_timeout_spin.setValue(s.timeout)
        self.search_timeout_spin.setSuffix(" 秒")
        self.search_timeout_spin.valueChanged.connect(lambda v: self._set("search", "timeout", v))
        self._row(adv, "请求超时", self.search_timeout_spin, stretch_last=False)

        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 5)
        self.retries_spin.setValue(s.max_retries)
        self.retries_spin.valueChanged.connect(lambda v: self._set("search", "max_retries", v))
        self._row(adv, "失败重试次数", self.retries_spin, stretch_last=False)

        layout.addStretch(1)
        return page

    # ---------- LLM ----------
    def _build_llm(self) -> QWidget:
        llm = self.settings.llm
        page, layout = self._page(
            "LLM 增强",
            "用于检索词规划与论文中文摘要/关键词生成（OpenAI 兼容接口）。不配置也可正常搜索，将自动降级。",
        )

        cred = self._group(layout, "接入")
        self.llm_enabled_check = QCheckBox("启用 LLM 增强（关闭后仅用搜索结果原文）")
        self.llm_enabled_check.setChecked(llm.enabled)
        self.llm_enabled_check.toggled.connect(lambda v: self._set("llm", "enabled", v))
        self._row(cred, "", self.llm_enabled_check)

        self.use_plan_check = QCheckBox("启用检索词规划（把中文方向自动转为英文检索式）")
        self.use_plan_check.setChecked(llm.use_plan)
        self.use_plan_check.toggled.connect(lambda v: self._set("llm", "use_plan", v))
        self._row(cred, "", self.use_plan_check)

        self.enrich_max_spin = QSpinBox()
        self.enrich_max_spin.setRange(0, 100)
        self.enrich_max_spin.setSpecialValueText("不限制")
        self.enrich_max_spin.setValue(llm.enrich_max_papers)
        self.enrich_max_spin.setToolTip("只为前 N 篇生成 LLM 摘要以控制耗时与配额，其余保留搜索摘要")
        self.enrich_max_spin.valueChanged.connect(
            lambda v: self._set("llm", "enrich_max_papers", v)
        )
        self._row(cred, "LLM 摘要篇数上限", self.enrich_max_spin, stretch_last=False)

        self.llm_url_edit = QLineEdit(llm.base_url)
        self.llm_url_edit.setPlaceholderText("例如 https://ark.cn-beijing.volces.com/api/coding/v3")
        self.llm_url_edit.textChanged.connect(lambda v: self._set("llm", "base_url", v))
        self._row(cred, "Base URL", self.llm_url_edit)

        self.llm_key_edit = self._key_field(cred, "llm", "api_key", llm.api_key)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setCurrentText(llm.model)
        self.model_combo.currentTextChanged.connect(lambda v: self._set("llm", "model", v))
        fetch_models = QPushButton("获取模型列表")
        fetch_models.setObjectName("secondaryButton")
        fetch_models.setCursor(Qt.PointingHandCursor)
        fetch_models.clicked.connect(self._fetch_models)
        self._row(cred, "模型", self.model_combo, fetch_models, stretch_last=False)

        test_row = QHBoxLayout()
        self.llm_test_btn = QPushButton("测试连接")
        self.llm_test_btn.setObjectName("primaryButton")
        self.llm_test_btn.setCursor(Qt.PointingHandCursor)
        self.llm_test_btn.clicked.connect(self._test_llm)
        self.llm_test_result = QLabel("")
        self.llm_test_result.setObjectName("hintLabel")
        self.llm_test_result.setWordWrap(True)
        test_row.addWidget(self.llm_test_btn)
        test_row.addWidget(self.llm_test_result, 1)
        cred.addLayout(test_row)

        gen = self._group(layout, "生成参数")
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 1.5)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(llm.temperature)
        self.temp_spin.valueChanged.connect(lambda v: self._set("llm", "temperature", v))
        self._row(gen, "Temperature", self.temp_spin, stretch_last=False)

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(128, 16384)
        self.max_tokens_spin.setSingleStep(128)
        self.max_tokens_spin.setValue(llm.max_tokens)
        self.max_tokens_spin.valueChanged.connect(lambda v: self._set("llm", "max_tokens", v))
        self._row(gen, "Max Tokens", self.max_tokens_spin, stretch_last=False)

        self.disable_thinking_check = QCheckBox("关闭思维链（推荐：摘要/规划类任务显著降延迟）")
        self.disable_thinking_check.setChecked(llm.disable_thinking)
        self.disable_thinking_check.toggled.connect(lambda v: self._set("llm", "disable_thinking", v))
        self._row(gen, "", self.disable_thinking_check)

        self.lang_combo = QComboBox()
        self.lang_combo.setEditable(True)
        self.lang_combo.addItems(["中文", "English", "日本語"])
        self.lang_combo.setCurrentText(llm.summary_language)
        self.lang_combo.currentTextChanged.connect(lambda v: self._set("llm", "summary_language", v))
        self._row(gen, "摘要语言", self.lang_combo, stretch_last=False)

        self.llm_timeout_spin = QSpinBox()
        self.llm_timeout_spin.setRange(5, 300)
        self.llm_timeout_spin.setValue(llm.timeout)
        self.llm_timeout_spin.setSuffix(" 秒")
        self.llm_timeout_spin.valueChanged.connect(lambda v: self._set("llm", "timeout", v))
        self._row(gen, "请求超时", self.llm_timeout_spin, stretch_last=False)

        layout.addStretch(1)
        return page

    # ---------- 网络 ----------
    def _build_network(self) -> QWidget:
        net = self.settings.network
        page, layout = self._page("网络", "代理与全局网络设置（搜索/抓取/下载共用）")
        group = self._group(layout, "代理")
        self.proxy_edit = QLineEdit(net.proxy)
        self.proxy_edit.setPlaceholderText("默认 http://127.0.0.1:7890（本机代理常见端口），可改可清空")
        self.proxy_edit.textChanged.connect(lambda v: self._set("network", "proxy", v))
        self._row(group, "HTTP 代理", self.proxy_edit)

        self.proxy_autodetect_check = QCheckBox("代理无人监听时自动回退直连（推荐开启，避免代理未启动时全部请求失败）")
        self.proxy_autodetect_check.setChecked(net.proxy_autodetect)
        self.proxy_autodetect_check.toggled.connect(lambda v: self._set("network", "proxy_autodetect", v))
        self._row(group, "", self.proxy_autodetect_check)

        self.direct_arxiv_check = QCheckBox("详情补全与论文配图直连 arxiv.org（免费、不占搜索配额）")
        self.direct_arxiv_check.setChecked(net.use_direct_arxiv)
        self.direct_arxiv_check.toggled.connect(lambda v: self._set("network", "use_direct_arxiv", v))
        self._row(group, "", self.direct_arxiv_check)
        self._hint(group, "若直连 arxiv.org 或搜索接口不畅，可在此配置代理。")

        layout.addStretch(1)
        return page

    # ---------- 关于 ----------
    def _build_about(self) -> QWidget:
        page, layout = self._page("关于", "")
        group = self._group(layout, "ArXiv Daily")
        lines = [
            f"版本：v{__version__}（开源项目，MIT License）",
            "一款黑白极简风的 arXiv 论文日报桌面应用：方向关键词 → 联网搜索 → 论文卡片 → 历史日报。",
            "技术栈：Python · PySide6 · LangGraph · 联网搜索 + LLM。",
        ]
        for text in lines:
            label = QLabel(text)
            label.setObjectName("hintLabel")
            label.setWordWrap(True)
            group.addWidget(label)

        key_group = self._group(layout, "联网搜索 API Key 获取步骤")
        steps = [
            "1. 登录腾讯云控制台（需实名认证），进入「元宝搜索」产品页并开通服务；",
            "2. 在「概览 → 服务 API KEY 方式」界面单击「创建 API KEY」；",
            "3. 复制弹窗中的密钥（sk- 开头，仅展示一次），粘贴到本页「联网搜索 → API Key」；",
            "4. 点击「测试连接」验证，成功后即可开始搜索。",
        ]
        for text in steps:
            label = QLabel(text)
            label.setObjectName("hintLabel")
            label.setWordWrap(True)
            key_group.addWidget(label)

        privacy = self._group(layout, "隐私与安全")
        notes = [
            "· 所有 API Key 仅保存在本机 ~/.arxiv_daily/settings.json，不会上传或包含在开源代码中；",
            "· 搜索历史与论文记录保存在本机 SQLite（~/.arxiv_daily/data.db），可随时在「历史记录」中删除。",
        ]
        for text in notes:
            label = QLabel(text)
            label.setObjectName("hintLabel")
            label.setWordWrap(True)
            privacy.addWidget(label)

        layout.addStretch(1)
        return page

    # ---------- 交互辅助 ----------
    def _on_nav(self, row: int):
        if self.stack.currentIndex() == row:
            return
        self.stack.setCurrentIndex(row)
        fade_in(self.stack.currentWidget(), duration=160)

    def _key_field(self, group, section: str, attr: str, value: str) -> QLineEdit:
        """密钥输入框：密码态 + 显示/隐藏切换。"""
        edit = QLineEdit(value)
        edit.setEchoMode(QLineEdit.Password)
        edit.setPlaceholderText("sk-…（仅保存在本机，不会进入代码仓库）")

        def toggle(checked: bool):
            edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

        eye = QPushButton("显示")
        eye.setObjectName("secondaryButton")
        eye.setCheckable(True)
        eye.setCursor(Qt.PointingHandCursor)
        eye.toggled.connect(toggle)
        eye.toggled.connect(lambda c: eye.setText("隐藏" if c else "显示"))
        edit.textChanged.connect(lambda v: self._set(section, attr, v))
        self._row(group, "API Key", edit, eye, stretch_last=False)
        return edit

    def _pick_download_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择下载目录", self.download_dir_edit.text())
        if path:
            self.download_dir_edit.setText(path)

    def _set(self, section: str, attr: str, value):
        setattr(getattr(self.settings, section), attr, value)
        save_settings(self.settings)
        self._flash_saved()
        self.settingsChanged.emit()

    def _flash_saved(self):
        for toast in getattr(self, "_toasts", []):
            toast.show()
        QTimer.singleShot(1200, lambda: [t.hide() for t in self._toasts])

    @staticmethod
    def _select_data(combo: QComboBox, data, fallback_index: int = 0):
        for i in range(combo.count()):
            if combo.itemData(i) == data:
                combo.setCurrentIndex(i)
                return
        combo.setCurrentIndex(fallback_index)

    # ---------- 测试连接 ----------
    def _run_func(self, fn, on_ok, on_error, button: QPushButton):
        if self._worker is not None and self._worker.isRunning():
            return
        button.setEnabled(False)
        self._worker = FuncWorker(fn)

        def ok(result):
            button.setEnabled(True)
            on_ok(result)

        def err(message):
            button.setEnabled(True)
            on_error(message)

        self._worker.finished_ok.connect(ok)
        self._worker.failed.connect(err)
        self._worker.start()

    def _current_search_settings(self):
        from ...config.settings import SearchSettings

        return SearchSettings(
            api_key=self.search_key_edit.text(),
            base_url=self.base_url_edit.text().strip() or "https://api.wsa.cloud.tencent.com",
            timeout=self.settings.search.timeout,
            max_retries=self.settings.search.max_retries,
        )

    def _test_search(self):
        provider = YuanbaoSearchProvider(self._current_search_settings(), proxy=self.settings.network.live_proxy())
        self.search_test_result.setText("测试中…")
        self._run_func(
            provider.test_connection,
            lambda msg: self._test_result(self.search_test_result, msg, True),
            lambda msg: self._test_result(self.search_test_result, msg, False),
            self.search_test_btn,
        )

    def _test_llm(self):
        from ...config.settings import LLMSettings

        llm_settings = LLMSettings(
            base_url=self.llm_url_edit.text().strip(),
            api_key=self.llm_key_edit.text(),
            model=self.model_combo.currentText().strip(),
            timeout=self.settings.llm.timeout,
        )
        client = LLMClient(llm_settings, proxy=self.settings.network.live_proxy())
        self.llm_test_result.setText("测试中…")
        self._run_func(
            client.test_connection,
            lambda msg: self._test_result(self.llm_test_result, msg, True),
            lambda msg: self._test_result(self.llm_test_result, msg, False),
            self.llm_test_btn,
        )

    def _fetch_models(self):
        from ...config.settings import LLMSettings

        llm_settings = LLMSettings(
            base_url=self.llm_url_edit.text().strip(),
            api_key=self.llm_key_edit.text(),
            timeout=30,
        )
        client = LLMClient(llm_settings, proxy=self.settings.network.live_proxy())
        self.llm_test_result.setText("获取模型列表中…")

        def ok(models):
            current = self.model_combo.currentText()
            self.model_combo.clear()
            self.model_combo.addItems(models)
            if current:
                self.model_combo.setCurrentText(current)
            self._test_result(self.llm_test_result, f"已获取 {len(models)} 个模型", True)

        self._run_func(
            client.list_models,
            ok,
            lambda msg: self._test_result(self.llm_test_result, msg, False),
            self.llm_test_btn,
        )

    @staticmethod
    def _test_result(label: QLabel, message: str, ok: bool):
        label.setObjectName("testResultOk" if ok else "testResultBad")
        label.setText(("✓ " if ok else "✗ ") + message)
        label.style().unpolish(label)
        label.style().polish(label)
