"""pytest 公共夹具。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def tmp_settings_path(tmp_path):
    return tmp_path / "settings.json"
