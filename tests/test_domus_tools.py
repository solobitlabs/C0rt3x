"""Testes unitarios para as tools Fast-Path do Domus Server e Edge Compute."""

import pytest

from cortex_core.core.cognitive_router import CognitiveRouter
from cortex_core.core.slave_power import SlavePowerManager
from cortex_core.tools.domus_tools import DomusTelemetryClient
from cortex_core.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_domus_telemetry_client_formats_summaries(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = {
        "host": {
            "cpu_percent": 14.2,
            "memory": {"percent": 48.5, "used_mb": 3584, "total_mb": 7372},
            "disk": {"percent": 31.0},
        },
        "containers": {"running": 18, "total": 19},
        "dns": {"queries_today": 12450, "blocked_today": 1890, "blocked_percent": 15.2},
        "compute_nodes": {
            "cortex-compute": {
                "online": True,
                "cpu": {"percent": 3.5},
                "memory": {"used_gb": 2.1, "total_gb": 15.0},
                "gpu": {
                    "busy_percent": 25.0,
                    "vram_used_mb": 4799.6,
                    "vram_total_mb": 8176.0,
                    "temp_c": 44.0,
                },
                "ollama": {"running_models": [{"name": "qwen2.5:7b"}]},
            }
        },
    }
    client = DomusTelemetryClient(dashboard_url="http://mock:8000")

    async def fake_fetch():
        return sample

    monkeypatch.setattr(client, "_fetch_stats", fake_fetch)

    server_txt = await client.server_summary()
    assert "CPU em 14.2%" in server_txt
    assert "18 de 19 containers" in server_txt

    compute_txt = await client.compute_summary()
    assert "RX 7600 em 25.0%" in compute_txt
    assert "qwen2.5:7b" in compute_txt

    dns_txt = await client.dns_summary()
    assert "12450 consultas" in dns_txt
    assert "15.2%" in dns_txt


@pytest.mark.asyncio
async def test_router_executes_domus_fast_path_tools() -> None:
    registry = ToolRegistry()

    async def fake_server() -> str:
        return "Domus Server OK"

    async def fake_compute() -> str:
        return "RX 7600 OK"

    async def fake_dns() -> str:
        return "DNS OK"

    registry.register("domus.stats.server", "Server stats", fake_server)
    registry.register("domus.stats.compute", "Compute stats", fake_compute)
    registry.register("domus.stats.dns", "DNS stats", fake_dns)

    slave = SlavePowerManager(slave_mac="", slave_host="")
    router = CognitiveRouter(tool_registry=registry, slave_power=slave)

    r1 = await router.route("Como esta o servidor agora?")
    assert r1.path == "fast_path"
    assert r1.tool_used == "domus.stats.server"
    assert r1.response_text == "Domus Server OK"

    r2 = await router.route("Qual a temperatura da GPU RX 7600?")
    assert r2.path == "fast_path"
    assert r2.tool_used == "domus.stats.compute"
    assert r2.response_text == "RX 7600 OK"

    r3 = await router.route("Quantos bloqueios o AdGuard fez hoje?")
    assert r3.path == "fast_path"
    assert r3.tool_used == "domus.stats.dns"
    assert r3.response_text == "DNS OK"
