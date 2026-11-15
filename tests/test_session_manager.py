"""Testes unitarios para SessionManager."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cortex_core.core.session_manager import SessionManager  # noqa: E402
from cortex_core.core.spatial_engine import SignalSource, SpatialEngine  # noqa: E402


class FakeClock:
    def __init__(self, initial: float = 500.0) -> None:
        self.now = initial

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_session_handoff_emits_handoff_in_before_speak() -> None:
    clock = FakeClock()
    spatial = SpatialEngine(clock=clock)
    sessions = SessionManager(spatial_engine=spatial, clock=clock)

    spatial.record_presence("will", "cozinha", "tab-cozinha", SignalSource.VOICE_SNR)
    sessions.append_turn("will", "user", "O que tem na despensa?", node_id="tab-cozinha", room="cozinha")

    # Will vai ate o banheiro enquanto a resposta e gerada
    clock.advance(4.0)
    spatial.record_presence("will", "banheiro", "kiosk-banheiro", SignalSource.CAMERA_MLKIT)

    plan = sessions.build_delivery_plan(
        "will",
        "Voce tem creme de leite vencendo em 2 dias.",
        expect_reply_seconds=8,
        summary_card={"title": "Despensa", "items": ["Creme de leite"]},
    )

    assert plan.handoff_occurred is True
    assert plan.target.node_id == "kiosk-banheiro"
    assert [cmd["action"] for cmd in plan.commands] == ["CORTEX_HANDOFF_IN", "CORTEX_SPEAK"]
    assert plan.commands[1]["payload"]["expect_reply_seconds"] == 8
    assert sessions.is_reply_window_active("will") is True

    clock.advance(9.0)
    assert sessions.is_reply_window_active("will") is False


def test_working_memory_truncates_to_max_turns() -> None:
    clock = FakeClock()
    spatial = SpatialEngine(clock=clock)
    sessions = SessionManager(spatial_engine=spatial, max_turns=3, clock=clock)

    for i in range(5):
        sessions.append_turn("will", "user", f"msg-{i}", node_id="tab-cozinha", room="cozinha")

    recent = sessions.get_recent_turns("will")
    assert [t.text for t in recent] == ["msg-2", "msg-3", "msg-4"]
