from arxiv_daily.config.settings import (
    LLMSettings,
    SearchSettings,
    Settings,
    load_settings,
    save_settings,
)


def test_defaults():
    s = Settings()
    assert s.general.start_page == "daily"
    assert s.search.save_history is True
    assert s.llm.use_plan is True
    assert s.llm.enrich_max_papers == 20
    assert s.network.use_direct_arxiv is True

    s = Settings()
    assert s.search.provider == "yuanbao"
    assert s.search.base_url.endswith("tencent.com")
    assert s.search.cnt == 20
    assert s.search.industry == "acad"
    assert not s.search.ready  # 无 key
    assert not s.llm.ready


def test_ready_when_key_present():
    s = Settings()
    s.search.api_key = "sk-test"
    assert s.search.ready
    s.llm.base_url = "https://x/v1"
    s.llm.api_key = "k"
    s.llm.model = "m"
    assert s.llm.ready
    s.llm.enabled = False
    assert not s.llm.ready


def test_roundtrip(tmp_settings_path):
    s = Settings()
    s.search.api_key = "sk-abc"
    s.llm.model = "deepseek-v4-flash"
    save_settings(s, tmp_settings_path)
    loaded = load_settings(tmp_settings_path)
    assert loaded.search.api_key == "sk-abc"
    assert loaded.llm.model == "deepseek-v4-flash"
    assert loaded.search.cnt == 20


def test_partial_and_unknown_keys_merged(tmp_settings_path):
    tmp_settings_path.write_text(
        '{"search": {"api_key": "sk-x", "cnt": 30}, "future_key": 1, "llm": {"model": "m"}}',
        encoding="utf-8",
    )
    s = load_settings(tmp_settings_path)
    assert s.search.api_key == "sk-x"
    assert s.search.cnt == 30
    assert s.search.mode == 2          # 未给的字段落回默认
    assert s.llm.model == "m"
    assert s.general.start_page == "daily"  # 未出现的整段用默认


def test_corrupted_file_falls_back(tmp_settings_path):
    tmp_settings_path.write_text("{not json", encoding="utf-8")
    s = load_settings(tmp_settings_path)
    assert s.search.api_key == ""


def test_live_proxy_states(monkeypatch):
    from arxiv_daily.config.settings import NetworkSettings
    from arxiv_daily.utils import net as net_mod

    n = NetworkSettings()
    assert n.proxy == "http://127.0.0.1:7890"          # 默认本机常见代理端口

    # 空 = 不用代理
    n.proxy = ""
    assert n.live_proxy() == ""

    # 端口无人监听 + autodetect → 回退直连
    n.proxy = "http://127.0.0.1:7890"
    monkeypatch.setattr(net_mod, "probe_proxy", lambda url, timeout=1.0: False)
    assert n.live_proxy() == ""

    # 探测通过 → 生效
    monkeypatch.setattr(net_mod, "probe_proxy", lambda url, timeout=1.0: True)
    assert n.live_proxy() == "http://127.0.0.1:7890"

    # 关闭 autodetect → 不探测，直接使用
    n.proxy_autodetect = False
    monkeypatch.setattr(net_mod, "probe_proxy", lambda url, timeout=1.0: False)
    assert n.live_proxy() == "http://127.0.0.1:7890"


def test_old_config_migrates_empty_proxy(tmp_settings_path):
    tmp_settings_path.write_text('{"network": {"proxy": ""}}', encoding="utf-8")
    s = load_settings(tmp_settings_path)
    assert s.network.proxy == "http://127.0.0.1:7890"   # 旧空值 → 默认本机代理
    # 用户显式清空后保存的新配置不再迁移
    save_settings(s, tmp_settings_path)
    tmp_settings_path.write_text(
        tmp_settings_path.read_text(encoding="utf-8").replace(
            '"http://127.0.0.1:7890"', '""'), encoding="utf-8")
    s2 = load_settings(tmp_settings_path)
    assert s2.network.proxy == ""                       # 已含 autodetect 键，不重复迁移
