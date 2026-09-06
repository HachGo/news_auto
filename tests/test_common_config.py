import importlib

import common
from common import load_config


def test_load_config_returns_dict(tmp_path):
    cfg = tmp_path / "f.yaml"
    cfg.write_text("settings:\n  total_limit: 3\nfeeds: []\n", encoding="utf-8")
    out = load_config(cfg)
    assert out["settings"]["total_limit"] == 3
    assert out["feeds"] == []


def test_default_model_is_deepseek_flash(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    importlib.reload(common)

    assert common.DEEPSEEK_MODEL == "deepseek-v4-flash"
