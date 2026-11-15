"""Motor espacial de presenca e roteamento Follow-Me entre comodos e Tailnet."""

from dataclasses import dataclass
from enum import Enum
import threading
import time
from typing import Callable, Dict, List, Optional


class SignalSource(str, Enum):
    """Fontes de sinal suportadas pelo SpatialEngine."""

    VOICE_SNR = "VOICE_SNR"
    CAMERA_MLKIT = "CAMERA_MLKIT"
    MMWAVE_RADAR = "MMWAVE_RADAR"
    LOCATION_EXTERNAL = "LOCATION_EXTERNAL"


@dataclass(frozen=True)
class SignalSpec:
    """Peso base e validade temporal (TTL) por tipo de sensor."""

    weight: float
    ttl_seconds: float


SIGNAL_SPECS: Dict[SignalSource, SignalSpec] = {
    SignalSource.VOICE_SNR: SignalSpec(weight=100.0, ttl_seconds=20.0),
    SignalSource.CAMERA_MLKIT: SignalSpec(weight=80.0, ttl_seconds=30.0),
    SignalSource.MMWAVE_RADAR: SignalSpec(weight=50.0, ttl_seconds=60.0),
    SignalSource.LOCATION_EXTERNAL: SignalSpec(weight=100.0, ttl_seconds=86400.0),
}

EXTERNAL_ZONE = "rua_tailnet"


@dataclass(frozen=True)
class PresenceSignal:
    """Registro imutavel de um sinal de presenca recebido."""

    user_id: str
    room: str
    node_id: str
    source: SignalSource
    confidence: float
    recorded_at: float


@dataclass(frozen=True)
class OutputTarget:
    """Destino selecionado para entrega da resposta ao morador."""

    zone: str
    node_id: Optional[str]
    channel: str  # "websocket" | "apprise_external"
    score: float


class SpatialEngine:
    """Calcula a localizacao provavel de cada morador e o melhor node de saida."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        # room -> lista ordenada de node_ids registrados naquele comodo
        self._room_nodes: Dict[str, List[str]] = {}
        # (user_id, room, source) -> PresenceSignal
        self._signals: Dict[tuple[str, str, SignalSource], PresenceSignal] = {}

    def register_node(self, node_id: str, room: str) -> None:
        """Associa um node de borda a uma zona fisica da residencia."""
        clean_node = node_id.strip()
        clean_room = room.strip().lower()
        if not clean_node or not clean_room:
            raise ValueError("node_id e room sao obrigatorios")
        with self._lock:
            nodes = self._room_nodes.setdefault(clean_room, [])
            if clean_node not in nodes:
                nodes.append(clean_node)

    def record_presence(
        self,
        user_id: str,
        room: str,
        node_id: str,
        source: SignalSource,
        confidence: float = 1.0,
    ) -> None:
        """Registra um sinal de presenca; limpa sinais externos ao retornar para casa."""
        clean_user = user_id.strip().lower()
        clean_room = room.strip().lower()
        clamped_conf = max(0.0, min(1.0, float(confidence)))
        now = self._clock()

        with self._lock:
            if clean_room != EXTERNAL_ZONE:
                self.register_node_unlocked(node_id=node_id, room=clean_room)
                # Morador detectado dentro de casa invalida presenca externa anterior
                self._signals.pop((clean_user, EXTERNAL_ZONE, SignalSource.LOCATION_EXTERNAL), None)

            key = (clean_user, clean_room, source)
            self._signals[key] = PresenceSignal(
                user_id=clean_user,
                room=clean_room,
                node_id=node_id.strip(),
                source=source,
                confidence=clamped_conf,
                recorded_at=now,
            )

    def register_node_unlocked(self, node_id: str, room: str) -> None:
        clean_node = node_id.strip()
        clean_room = room.strip().lower()
        if clean_node and clean_room:
            nodes = self._room_nodes.setdefault(clean_room, [])
            if clean_node not in nodes:
                nodes.append(clean_node)

    def get_room_scores(self, user_id: str) -> Dict[str, float]:
        """Retorna a pontuacao atual de cada zona para o morador, aplicando decaimento TTL."""
        clean_user = user_id.strip().lower()
        now = self._clock()
        scores: Dict[str, float] = {}
        expired_keys: List[tuple[str, str, SignalSource]] = []

        with self._lock:
            for key, sig in self._signals.items():
                if sig.user_id != clean_user:
                    continue
                spec = SIGNAL_SPECS[sig.source]
                age = max(0.0, now - sig.recorded_at)
                if age >= spec.ttl_seconds:
                    expired_keys.append(key)
                    continue
                decay = 1.0 - (age / spec.ttl_seconds)
                contribution = round(spec.weight * sig.confidence * decay, 2)
                scores[sig.room] = round(scores.get(sig.room, 0.0) + contribution, 2)

            for k in expired_keys:
                self._signals.pop(k, None)

        return scores

    def get_best_output_target(
        self,
        user_id: str,
        fallback_node_id: Optional[str] = None,
    ) -> OutputTarget:
        """Seleciona o melhor canal/node de entrega para o morador neste instante."""
        scores = self.get_room_scores(user_id)
        if not scores:
            return OutputTarget(
                zone="unknown",
                node_id=fallback_node_id,
                channel="websocket" if fallback_node_id else "apprise_external",
                score=0.0,
            )

        # Desempate por sinal mais recente na zona vencedora
        with self._lock:
            clean_user = user_id.strip().lower()
            zone_latest: Dict[str, float] = {}
            for sig in self._signals.values():
                if sig.user_id == clean_user and sig.room in scores:
                    prev = zone_latest.get(sig.room, -1.0)
                    if sig.recorded_at > prev:
                        zone_latest[sig.room] = sig.recorded_at

        best_zone, best_score = max(
            scores.items(),
            key=lambda item: (item[1], zone_latest.get(item[0], -1.0)),
        )
        if best_zone == EXTERNAL_ZONE:
            return OutputTarget(
                zone=EXTERNAL_ZONE,
                node_id=None,
                channel="apprise_external",
                score=best_score,
            )

        with self._lock:
            # Prefere o node que emitiu o sinal mais recente nessa zona
            latest_node: Optional[str] = None
            latest_ts = -1.0
            clean_user = user_id.strip().lower()
            for sig in self._signals.values():
                if sig.user_id == clean_user and sig.room == best_zone and sig.recorded_at > latest_ts:
                    latest_ts = sig.recorded_at
                    latest_node = sig.node_id

            if not latest_node:
                candidates = self._room_nodes.get(best_zone, [])
                latest_node = candidates[0] if candidates else fallback_node_id

        return OutputTarget(
            zone=best_zone,
            node_id=latest_node,
            channel="websocket",
            score=best_score,
        )
