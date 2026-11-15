"""Unit tests for domus-cortex-daemon telemetry collection."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


def _ensure_psutil_or_stub() -> None:
    if "psutil" in sys.modules:
        return
    try:
        import psutil  # noqa: F401
    except ImportError:
        stub = types.ModuleType("psutil")
        stub.PROCFS_PATH = "/proc"
        stub.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        stub.AccessDenied = type("AccessDenied", (Exception,), {})
        stub.ZombieProcess = type("ZombieProcess", (Exception,), {})
        stub.cpu_percent = lambda interval=None: 12.5
        stub.cpu_count = lambda logical=True: 12 if logical else 6
        stub.virtual_memory = lambda: types.SimpleNamespace(
            percent=40.0, used=6 * 1024**3, total=15 * 1024**3
        )
        stub.swap_memory = lambda: types.SimpleNamespace(percent=0.0)
        stub.disk_usage = lambda path: types.SimpleNamespace(
            percent=25.0, used=100 * 1024**3, total=400 * 1024**3
        )
        stub.boot_time = lambda: 1700000000.0
        stub.sensors_temperatures = lambda: {}
        stub.process_iter = lambda attrs=None: [
            types.SimpleNamespace(
                info={
                    "pid": 1,
                    "name": "systemd",
                    "cpu_percent": 0.1,
                    "memory_info": types.SimpleNamespace(rss=12 * 1024 * 1024),
                    "status": "sleeping",
                }
            )
        ]
        sys.modules["psutil"] = stub


def _load_daemon_module():
    _ensure_psutil_or_stub()
    daemon_path = Path(__file__).resolve().parents[1] / "daemon" / "daemon.py"
    spec = importlib.util.spec_from_file_location("domus_cortex_daemon", daemon_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_collect_amd_gpu_metrics_from_sysfs_mock(tmp_path: Path) -> None:
    mod = _load_daemon_module()
    dev = tmp_path / "card1" / "device"
    hw = dev / "hwmon" / "hwmon5"
    hw.mkdir(parents=True)
    (dev / "gpu_busy_percent").write_text("42\n", encoding="utf-8")
    (dev / "mem_info_vram_used").write_text(str(2048 * 1024 * 1024), encoding="utf-8")
    (dev / "mem_info_vram_total").write_text(str(8192 * 1024 * 1024), encoding="utf-8")
    (hw / "temp1_input").write_text("54000\n", encoding="utf-8")
    (hw / "power1_average").write_text("38500000\n", encoding="utf-8")

    gpu = mod.collect_amd_gpu_metrics(tmp_path)
    assert gpu["available"] is True
    assert gpu["busy_percent"] == 42.0
    assert gpu["vram_used_mb"] == 2048.0
    assert gpu["vram_total_mb"] == 8192.0
    assert gpu["vram_percent"] == 25.0
    assert gpu["temp_c"] == 54.0
    assert gpu["power_watts"] == 38.5


def test_build_telemetry_snapshot_has_required_sections() -> None:
    mod = _load_daemon_module()
    snap = mod.build_telemetry_snapshot()
    for key in ("node_id", "timestamp", "cpu", "memory", "disk", "gpu", "processes", "containers", "ollama"):
        assert key in snap
    assert snap["processes"]["total_count"] >= 1
