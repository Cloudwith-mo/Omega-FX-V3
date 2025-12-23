from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from ftmo_bot.config import freeze_config, load_config, verify_config_lock
from ftmo_bot.rule_engine import AccountStage


def test_load_config_sample():
    config = load_config(Path("configs") / "ftmo_v1.yaml")
    assert config.rule_spec.stage == AccountStage.CHALLENGE
    assert "EURUSD" in config.instruments


def test_freeze_and_verify(tmp_path):
    source = Path("configs") / "ftmo_v1.yaml"
    target = tmp_path / "ftmo_v1.yaml"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    lock_path = freeze_config(target)
    assert verify_config_lock(target, lock_path)
