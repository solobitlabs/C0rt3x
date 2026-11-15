"""Gerenciador de sessoes centrado no morador com suporte a handoff e expect_reply."""

from dataclasses import dataclass, field
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from cortex_core.core.spatial_engine import OutputTarget, SpatialEngine


@dataclass
class DialogueTurn:
    """Turno individual na memoria de trabalho da sessao."""

    role: str  # "user" | "assistant" | "system"
    text: str
    node_id: Optional[str]
    timestamp: float


@dataclass
class UserSession:
    """Estado ativo de conversa indexado por morador."""

    session_id: str
    user_id: str
    origin_node_id: Optional[str]
    origin_room: str
    active_output_node_id: Optional[str]
    created_at: float
    updated_at: float
    expect_reply_until: float = 0.0
    turns: List[DialogueTurn] = field(default_factory=list)


@dataclass(frozen=True)
class DeliveryPlan:
    """Plano de entrega calculado no momento do dispatch da resposta."""

    session_id: str
    target: OutputTarget
    handoff_occurred: bool
    commands: List[Dict[str, Any]]


class SessionManager:
    """Mantem sessoes por morador e orquestra handoff espacial na entrega."""

    def __init__(
        self,
        spatial_engine: SpatialEngine,
        max_turns: int = 10,
        session_ttl_seconds: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._spatial = spatial_engine
        self._max_turns = max_turns
        self._session_ttl = session_ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: Dict[str, UserSession] = {}

    def open_or_get_session(
        self,
        user_id: str,
        origin_node_id: Optional[str] = None,
        origin_room: str = "unknown",
    ) -> UserSession:
        """Recupera sessao ativa do morador ou cria uma nova se expirada."""
        clean_user = user_id.strip().lower()
        now = self._clock()

        with self._lock:
            existing = self._sessions.get(clean_user)
            if existing and (now - existing.updated_at) <= self._session_ttl:
                existing.updated_at = now
                return existing

            session = UserSession(
                session_id=f"sess-{clean_user}-{uuid.uuid4().hex[:8]}",
                user_id=clean_user,
                origin_node_id=origin_node_id,
                origin_room=origin_room,
                active_output_node_id=origin_node_id,
                created_at=now,
                updated_at=now,
            )
            self._sessions[clean_user] = session
            return session

    def append_turn(
        self,
        user_id: str,
        role: str,
        text: str,
        node_id: Optional[str] = None,
        room: str = "unknown",
    ) -> UserSession:
        """Adiciona uma fala a memoria de trabalho limitada da sessao."""
        session = self.open_or_get_session(user_id=user_id, origin_node_id=node_id, origin_room=room)
        now = self._clock()
        with self._lock:
            session.turns.append(
                DialogueTurn(role=role, text=text, node_id=node_id, timestamp=now)
            )
            if len(session.turns) > self._max_turns:
                session.turns = session.turns[-self._max_turns :]
            session.updated_at = now
        return session

    def get_recent_turns(self, user_id: str) -> List[DialogueTurn]:
        """Retorna copia segura dos turnos recentes da sessao."""
        clean_user = user_id.strip().lower()
        with self._lock:
            sess = self._sessions.get(clean_user)
            return list(sess.turns) if sess else []

    def is_reply_window_active(self, user_id: str) -> bool:
        """Indica se o morador esta dentro da janela de resposta sem wake-word."""
        clean_user = user_id.strip().lower()
        now = self._clock()
        with self._lock:
            sess = self._sessions.get(clean_user)
            return bool(sess and now <= sess.expect_reply_until)

    def build_delivery_plan(
        self,
        user_id: str,
        text: str,
        expect_reply_seconds: int = 0,
        audio_url: Optional[str] = None,
        summary_card: Optional[Dict[str, Any]] = None,
    ) -> DeliveryPlan:
        """Calcula o destino atual do morador e gera comandos WebSocket/externos."""
        session = self.open_or_get_session(user_id=user_id)
        target = self._spatial.get_best_output_target(
            user_id=user_id,
            fallback_node_id=session.active_output_node_id or session.origin_node_id,
        )
        now = self._clock()
        commands: List[Dict[str, Any]] = []
        handoff_occurred = False

        with self._lock:
            previous_node = session.active_output_node_id
            if target.channel == "websocket" and target.node_id:
                if previous_node and previous_node != target.node_id:
                    handoff_occurred = True
                    commands.append(
                        {
                            "command_id": f"cmd-handoff-{uuid.uuid4().hex[:8]}",
                            "action": "CORTEX_HANDOFF_IN",
                            "target_node_id": target.node_id,
                            "payload": {
                                "session_id": session.session_id,
                                "origin_room": session.origin_room,
                                "wake_screen_softly": True,
                                "summary_card": summary_card,
                            },
                        }
                    )
                session.active_output_node_id = target.node_id

            speak_payload: Dict[str, Any] = {
                "session_id": session.session_id,
                "text": text,
                "show_hud": True,
                "expect_reply_seconds": max(0, int(expect_reply_seconds)),
            }
            if audio_url:
                speak_payload["audio_url"] = audio_url

            if target.channel == "websocket" and target.node_id:
                commands.append(
                    {
                        "command_id": f"cmd-speak-{uuid.uuid4().hex[:8]}",
                        "action": "CORTEX_SPEAK",
                        "target_node_id": target.node_id,
                        "payload": speak_payload,
                    }
                )

            if expect_reply_seconds > 0:
                session.expect_reply_until = now + float(expect_reply_seconds)
            session.updated_at = now

        return DeliveryPlan(
            session_id=session.session_id,
            target=target,
            handoff_occurred=handoff_occurred,
            commands=commands,
        )
