from pathlib import Path
from common import load_config


def test_load_config_returns_dict(tmp_path):
    cfg = tmp_path / "f.yaml"
    cfg.write_text("settings:\n  total_limit: 3\nfeeds: []\n", encoding="utf-8")
    out = load_config(cfg)
    assert out["settings"]["total_limit"] == 3
    assert out["feeds"] == []
