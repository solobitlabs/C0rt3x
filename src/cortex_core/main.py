"""Gateway FastAPI e WebSocket Full-Duplex v2 do Domus C0rt3x Core."""

import asyncio
from contextlib import asynccontextmanager
import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from cortex_core import __version__
from cortex_core.config import CortexSettings, get_settings
from cortex_core.core.cognitive_router import CognitiveRouter
from cortex_core.core.memory_engine import MemoryEngine
from cortex_core.core.session_manager import SessionManager
from cortex_core.core.slave_power import SlavePowerManager
from cortex_core.core.spatial_engine import SignalSource, SpatialEngine
from cortex_core.tools.domus_tools import DomusTelemetryClient
from cortex_core.tools.notify_tool import AppriseNotifier
from cortex_core.tools.registry import ToolRegistry

logger = logging.getLogger("cortex.api")


class NodeWebSocketGateway:
    """Gerencia conexoes WebSocket ativas dos nodes Android/Kiosk."""

    def __init__(self) -> None:
        self._connections: Dict[str, WebSocket] = {}

    async def connect(self, node_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[node_id] = websocket
        logger.info("Node conectado via WebSocket: %s", node_id)

    def disconnect(self, node_id: str, websocket: WebSocket) -> None:
        if self._connections.get(node_id) is websocket:
            self._connections.pop(node_id, None)
            logger.info("Node desconectado: %s", node_id)

    async def send_command(self, node_id: str, command: Dict[str, Any]) -> bool:
        ws = self._connections.get(node_id)
        if ws is None:
            return False
        try:
            await ws.send_json(command)
            return True
        except Exception as exc:
            logger.warning("Falha ao enviar comando para %s: %s", node_id, exc)
            self._connections.pop(node_id, None)
            return False

    def connected_node_ids(self) -> List[str]:
        return sorted(self._connections.keys())


class InteractRequest(BaseModel):
    user_id: str = Field(default="will", min_length=1, max_length=64)
    transcript: str = Field(..., min_length=1, max_length=2000)
    node_id: Optional[str] = Field(default=None, max_length=128)
    room: str = Field(default="cozinha", min_length=1, max_length=64)


class CortexRuntime:
    """Agrega os modulos do C0rt3x Core em uma instancia coesa."""

    def __init__(self, settings: CortexSettings) -> None:
        self.settings = settings
        self.spatial = SpatialEngine()
        self.sessions = SessionManager(spatial_engine=self.spatial)
        self.slave_power = SlavePowerManager(
            slave_mac=settings.slave_mac,
            slave_host=settings.slave_host,
            slave_port=settings.slave_port,
            slave_api_token=settings.slave_api_token,
            broadcast_ip=settings.slave_broadcast_ip,
            wol_port=settings.slave_wol_port,
            idle_timeout_seconds=settings.slave_idle_timeout_seconds,
            wake_timeout_seconds=settings.slave_wake_timeout_seconds,
        )
        self.tools = ToolRegistry()
        self.notifier = AppriseNotifier(
            apprise_url=settings.apprise_url,
            default_tag=settings.apprise_default_tag,
        )
        self.domus_telemetry = DomusTelemetryClient()
        self.router = CognitiveRouter(tool_registry=self.tools, slave_power=self.slave_power)
        self.memory = MemoryEngine(database_url=settings.database_url)
        self.ws_gateway = NodeWebSocketGateway()
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        self.tools.register(
            "notify.send_external",
            "Envia notificacao externa via Apprise (Telegram/E-mail).",
            self.notifier.send,
        )
        self.tools.register(
            "domus.stats.server",
            "Consulta CPU, RAM, disco e containers do Domus Server.",
            self.domus_telemetry.server_summary,
        )
        self.tools.register(
            "domus.stats.compute",
            "Consulta CPU, RAM, GPU RX 7600, VRAM e Ollama do C0rt3x Compute.",
            self.domus_telemetry.compute_summary,
        )
        self.tools.register(
            "domus.stats.dns",
            "Consulta metricas de consultas e bloqueios do AdGuard DNS.",
            self.domus_telemetry.dns_summary,
        )


def create_app(settings: Optional[CortexSettings] = None) -> FastAPI:
    cfg = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    runtime = CortexRuntime(cfg)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await runtime.memory.initialize()
        reaper_stop = asyncio.Event()

        async def _idle_reaper() -> None:
            while not reaper_stop.is_set():
                await asyncio.sleep(60)
                await runtime.slave_power.sleep_if_idle()

        reaper_task = asyncio.create_task(_idle_reaper())
        try:
            yield
        finally:
            reaper_stop.set()
            reaper_task.cancel()
            await runtime.memory.close()

    app = FastAPI(
        title=cfg.app_name,
        version=__version__,
        lifespan=lifespan,
    )
    app.state.cortex = runtime

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "postgres_connected": runtime.memory.using_postgres,
            "slave": runtime.slave_power.status_snapshot(),
            "connected_nodes": runtime.ws_gateway.connected_node_ids(),
        }

    @app.get("/api/cortex/status")
    async def status() -> Dict[str, Any]:
        return {
            "version": __version__,
            "config": runtime.settings.redacted_summary(),
            "slave": runtime.slave_power.status_snapshot(),
            "connected_nodes": runtime.ws_gateway.connected_node_ids(),
            "tools": runtime.tools.list_tools(),
        }

    @app.post("/api/cortex/interact")
    async def interact(req: InteractRequest) -> Dict[str, Any]:
        if req.node_id:
            runtime.spatial.record_presence(
                user_id=req.user_id,
                room=req.room,
                node_id=req.node_id,
                source=SignalSource.VOICE_SNR,
            )

        runtime.sessions.append_turn(
            user_id=req.user_id,
            role="user",
            text=req.transcript,
            node_id=req.node_id,
            room=req.room,
        )
        recent_turns = [
            {"role": t.role, "text": t.text}
            for t in runtime.sessions.get_recent_turns(req.user_id)
        ]
        memories = await runtime.memory.search_semantic_memories(
            user_id=req.user_id,
            query_text=req.transcript,
            limit=5,
        )

        decision = await runtime.router.route(
            transcript=req.transcript,
            room=req.room,
            recent_turns=recent_turns,
            memories=memories,
        )
        runtime.sessions.append_turn(
            user_id=req.user_id,
            role="assistant",
            text=decision.response_text,
            node_id=req.node_id,
            room=req.room,
        )

        plan = runtime.sessions.build_delivery_plan(
            user_id=req.user_id,
            text=decision.response_text,
            expect_reply_seconds=decision.expect_reply_seconds,
        )

        delivered_via_ws = False
        if plan.target.channel == "websocket" and plan.target.node_id:
            for cmd in plan.commands:
                delivered_via_ws = await runtime.ws_gateway.send_command(plan.target.node_id, cmd)
        elif plan.target.channel == "apprise_external":
            await runtime.notifier.send(title="Domus C0rt3x", body=decision.response_text)

        return {
            "session_id": plan.session_id,
            "path": decision.path,
            "tool_used": decision.tool_used,
            "response_text": decision.response_text,
            "handoff_occurred": plan.handoff_occurred,
            "target": {
                "zone": plan.target.zone,
                "node_id": plan.target.node_id,
                "channel": plan.target.channel,
                "score": plan.target.score,
            },
            "delivered_via_ws": delivered_via_ws,
            "commands": plan.commands,
        }

    @app.websocket("/api/nodes/{node_id}/channel")
    async def node_channel(websocket: WebSocket, node_id: str) -> None:
        clean_id = node_id.strip()
        await runtime.ws_gateway.connect(clean_id, websocket)
        try:
            while True:
                msg = await websocket.receive_json()
                if not isinstance(msg, dict):
                    continue
                if msg.get("type") != "CORTEX_EVENT":
                    continue

                event_name = str(msg.get("event", "")).strip()
                room = str(msg.get("room", "unknown")).strip().lower()
                payload = msg.get("payload") or {}
                user_id = str(payload.get("person_hint") or payload.get("user") or "will")

                if event_name == "PRESENCE_DETECTED":
                    runtime.spatial.record_presence(
                        user_id=user_id,
                        room=room,
                        node_id=clean_id,
                        source=SignalSource.CAMERA_MLKIT,
                        confidence=float(payload.get("confidence", 0.9)),
                    )
                elif event_name == "LOCATION_STATE_CHANGED":
                    if payload.get("home_present") is False:
                        runtime.spatial.record_presence(
                            user_id=user_id,
                            room="rua_tailnet",
                            node_id=clean_id,
                            source=SignalSource.LOCATION_EXTERNAL,
                        )
                elif event_name == "WAKE_WORD_DETECTED":
                    runtime.spatial.record_presence(
                        user_id=user_id,
                        room=room,
                        node_id=clean_id,
                        source=SignalSource.VOICE_SNR,
                    )
        except WebSocketDisconnect:
            runtime.ws_gateway.disconnect(clean_id, websocket)
        except Exception as exc:
            logger.warning("Erro no canal WebSocket de %s: %s", clean_id, exc)
            runtime.ws_gateway.disconnect(clean_id, websocket)

    return app


app = create_app()
