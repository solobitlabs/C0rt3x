"""Testes unitarios para SlavePowerManager (WoL S3 e auto-sleep)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cortex_core.core.slave_power import (  # noqa: E402
    SlavePowerManager,
    SlaveState,
    build_magic_packet,
)


class FakeClock:
    def __init__(self, initial: float = 1000.0) -> None:
        self.now = initial

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_magic_packet_format() -> None:
    pkt = build_magic_packet("AA:BB:CC:DD:EE:FF")
    assert len(pkt) == 102
    assert pkt[:6] == b"\xff" * 6
    assert pkt[6:12] == bytes.fromhex("AABBCCDDEEFF")

    with pytest.raises(ValueError):
        build_magic_packet("invalid")


@pytest.mark.asyncio
async def test_wake_on_lan_and_idle_sleep_cycle() -> None:
    clock = FakeClock()
    wol_calls: list[tuple[str, str, int]] = []
    sleep_calls: list[str] = []
    probe_attempts = 0

    async def fake_probe(url: str) -> bool:
        nonlocal probe_attempts
        probe_attempts += 1
        # Primeira checagem falha (dormindo); apos WoL responde True
        return probe_attempts >= 2

    async def fake_sleep(url: str) -> bool:
        sleep_calls.append(url)
        return True

    mgr = SlavePowerManager(
        slave_mac="AA:BB:CC:DD:EE:FF",
        slave_host="192.168.x.50",
        idle_timeout_seconds=600,
        wake_timeout_seconds=5.0,
        poll_interval_seconds=0.01,
        clock=clock,
        wol_sender=lambda mac, bcast, port: wol_calls.append((mac, bcast, port)),
        health_probe=fake_probe,
        sleep_trigger=fake_sleep,
    )

    assert mgr.state == SlaveState.SLEEPING_S3
    ok = await mgr.ensure_online()
    assert ok is True
    assert mgr.state == SlaveState.ONLINE_IDLE
    assert len(wol_calls) == 1

    # Antes de 600s nao dorme
    clock.advance(300.0)
    assert await mgr.sleep_if_idle() is False

    # Apos 600s envia comando de suspensao S3
    clock.advance(301.0)
    assert await mgr.sleep_if_idle() is True
    assert mgr.state == SlaveState.SLEEPING_S3
    assert len(sleep_calls) == 1
