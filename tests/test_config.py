"""Testes unitarios para CortexSettings."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cortex_core.config import CortexSettings  # noqa: E402


def test_default_settings_and_redaction() -> None:
    cfg = CortexSettings(
        database_url="postgresql://cortex_app:secret@postgres-domus:5432/cortex_db",
        despensa_api_token="tok-123",
    )
    summary = cfg.redacted_summary()
    assert summary["database_configured"] is True
    assert summary["despensa_configured"] is True
    assert "secret" not in str(summary)
    assert "tok-123" not in str(summary)


def test_mac_normalization_and_validation() -> None:
    cfg = CortexSettings(slave_mac="aa-bb-cc-dd-ee-ff")
    assert cfg.slave_mac == "AA:BB:CC:DD:EE:FF"

    with pytest.raises(ValueError):
        CortexSettings(slave_mac="invalid-mac")


def test_log_level_validation() -> None:
    cfg = CortexSettings(log_level="debug")
    assert cfg.log_level == "DEBUG"

    with pytest.raises(ValueError):
        CortexSettings(log_level="VERBOSE")
