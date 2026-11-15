"""Testes unitarios para SpatialEngine e handoff Follow-Me."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cortex_core.core.spatial_engine import SignalSource, SpatialEngine  # noqa: E402


class FakeClock:
    def __init__(self, initial: float = 100.0) -> None:
        self.now = initial

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_follow_me_handoff_from_kitchen_to_bathroom() -> None:
    clock = FakeClock()
    spatial = SpatialEngine(clock=clock)

    # t=0: Will fala na cozinha
    spatial.record_presence("will", "cozinha", "tab-cozinha", SignalSource.VOICE_SNR, confidence=1.0)
    target = spatial.get_best_output_target("will")
    assert target.zone == "cozinha"
    assert target.node_id == "tab-cozinha"
    assert target.channel == "websocket"

    # t=6s: Will passa pela sala (mmWave) e para no espelho do banheiro (ML Kit)
    clock.advance(6.0)
    spatial.record_presence("will", "sala", "sensor-sala", SignalSource.MMWAVE_RADAR, confidence=1.0)
    spatial.record_presence("will", "banheiro", "kiosk-banheiro", SignalSource.CAMERA_MLKIT, confidence=0.95)

    target_after = spatial.get_best_output_target("will")
    assert target_after.zone == "banheiro"
    assert target_after.node_id == "kiosk-banheiro"
    assert target_after.channel == "websocket"


def test_ttl_expiration_and_external_tailnet_transition() -> None:
    clock = FakeClock()
    spatial = SpatialEngine(clock=clock)

    spatial.record_presence("will", "cozinha", "tab-cozinha", SignalSource.VOICE_SNR)
    # Avanca alem do TTL de VOICE_SNR (20s)
    clock.advance(25.0)
    assert spatial.get_room_scores("will") == {}

    # Saiu de casa -> rota externa via Apprise
    spatial.record_presence("will", "rua_tailnet", "mobile-will", SignalSource.LOCATION_EXTERNAL)
    target_ext = spatial.get_best_output_target("will")
    assert target_ext.zone == "rua_tailnet"
    assert target_ext.channel == "apprise_external"

    # Retornou para casa -> sinal externo e invalidado automaticamente
    clock.advance(5.0)
    spatial.record_presence("will", "sala", "tv-sala", SignalSource.CAMERA_MLKIT)
    target_home = spatial.get_best_output_target("will")
    assert target_home.zone == "sala"
    assert target_home.channel == "websocket"
