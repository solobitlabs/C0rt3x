"""Testes unitarios para CognitiveRouter e ToolRegistry."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cortex_core.core.cognitive_router import CognitiveRouter  # noqa: E402
from cortex_core.core.slave_power import SlavePowerManager  # noqa: E402
from cortex_core.tools.registry import ToolRegistry  # noqa: E402


@pytest.mark.asyncio
async def test_fast_path_executes_without_waking_gpu_slave() -> None:
    registry = ToolRegistry()
    executed: list[tuple[str, dict]] = []

    async def fake_play(query: str, zone: str) -> None:
        executed.append(("media.play", {"query": query, "zone": zone}))

    registry.register("media.play", "Toca faixa em zona", fake_play)

    wol_called = False
    slave = SlavePowerManager(
        slave_mac="AA:BB:CC:DD:EE:FF",
        slave_host="192.168.x.50",
        wol_sender=lambda *_: None,
        health_probe=lambda *_: _false(),
    )

    async def _false() -> bool:
        nonlocal wol_called
        wol_called = True
        return False

    router = CognitiveRouter(tool_registry=registry, slave_power=slave)
    res = await router.route("Reproduza Fireside no quarto", room="sala")

    assert res.path == "fast_path"
    assert res.tool_used == "media.play"
    assert "quarto" in res.response_text
    assert executed == [("media.play", {"query": "Fireside", "zone": "quarto"})]
    assert wol_called is False


@pytest.mark.asyncio
async def test_slow_path_wakes_slave_and_runs_inference() -> None:
    registry = ToolRegistry()
    wol_calls = 0

    async def probe_ok(_url: str) -> bool:
        return True

    slave = SlavePowerManager(
        slave_mac="AA:BB:CC:DD:EE:FF",
        slave_host="192.168.x.50",
        wol_sender=lambda *_: None,
        health_probe=probe_ok,
    )

    async def fake_infer(prompt: str, turns: list, memories: list) -> str:
        nonlocal wol_calls
        wol_calls += 1
        return f"Sugestao de receita para: {prompt}"

    router = CognitiveRouter(tool_registry=registry, slave_power=slave, slave_infer_fn=fake_infer)
    res = await router.route("O que posso cozinhar com creme de leite vencendo?", room="cozinha")

    assert res.path == "slow_path"
    assert "Sugestao de receita" in res.response_text
    assert wol_calls == 1
