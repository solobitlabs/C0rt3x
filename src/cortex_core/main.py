"""Gateway FastAPI e WebSocket Full-Duplex v2 do Domus C0rt3x Core."""

import asyncio
import base64
from contextlib import asynccontextmanager
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
import httpx
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

    async def embed_text(self, text: str) -> Optional[List[float]]:
        """Solicita embedding ao C0rt3x Compute quando disponivel; retorna None em fallback."""
        if not self.slave_power.base_url:
            return None
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.post(
                    f"{self.slave_power.base_url}/api/embed",
                    json={"text": text},
                    headers=self.slave_power.auth_headers,
                )
                if resp.status_code == 200:
                    vec = resp.json().get("embedding")
                    if isinstance(vec, list) and vec:
                        return [float(x) for x in vec]
        except Exception as exc:
            logger.debug("Embedding via slave indisponivel (usando fallback lexical): %s", exc)
        return None


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

    @app.get("/api/cortex/memories")
    async def list_memories(user_id: str = "will", limit: int = 20) -> Dict[str, Any]:
        facts = await runtime.memory.list_semantic_memories(user_id=user_id, limit=limit)
        return {"user_id": user_id, "count": len(facts), "memories": facts}

    async def _run_interaction(req: InteractRequest) -> Dict[str, Any]:
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

        mem_match = re.match(
            r"^\s*(?:lembr[ae]\w*|memoriz\w*|anot[ae]\w*|guard[ae]\w*)\s+(?:na\s+mem[oó]ria\s+)?(?:que\s+)?(.+)$",
            req.transcript,
            re.I,
        )
        if mem_match:
            fact = mem_match.group(1).strip()
            emb = await runtime.embed_text(fact)
            await runtime.memory.save_semantic_memory(req.user_id, fact, embedding=emb)
            from cortex_core.core.cognitive_router import RouteDecision

            decision = RouteDecision(
                path="fast_path",
                response_text=f"Anotado na memoria: {fact}",
                tool_used="memory.save",
            )
        else:
            query_emb = await runtime.embed_text(req.transcript)
            memories = await runtime.memory.search_semantic_memories(
                user_id=req.user_id,
                query_embedding=query_emb,
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

    @app.post("/api/cortex/interact")
    async def interact(req: InteractRequest) -> Dict[str, Any]:
        return await _run_interaction(req)

    @app.post("/api/cortex/stt")
    async def stt(request: Request) -> Dict[str, Any]:
        if not runtime.slave_power.base_url:
            raise HTTPException(status_code=503, detail="C0rt3x Compute nao configurado")
        raw = await request.body()
        if not raw:
            raise HTTPException(status_code=400, detail="Audio vazio")
        ctype = request.headers.get("content-type", "audio/webm")
        headers = dict(runtime.slave_power.auth_headers)
        headers["Content-Type"] = ctype
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{runtime.slave_power.base_url}/api/stt",
                content=raw,
                headers=headers,
            )
            if resp.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"STT falhou: {resp.text}")
            return resp.json()

    @app.post("/api/cortex/tts")
    async def tts(payload: Dict[str, str]) -> Response:
        if not runtime.slave_power.base_url:
            raise HTTPException(status_code=503, detail="C0rt3x Compute nao configurado")
        text = str(payload.get("text", "")).strip()
        if not text:
            raise HTTPException(status_code=400, detail="Texto vazio")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{runtime.slave_power.base_url}/api/tts",
                json={"text": text},
                headers=runtime.slave_power.auth_headers,
            )
            if resp.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"TTS falhou: {resp.text}")
            return Response(content=resp.content, media_type="audio/wav")

    @app.post("/api/cortex/voice")
    async def voice_interact(
        request: Request,
        user_id: str = "will",
        room: str = "sala",
        speak: bool = True,
    ) -> Dict[str, Any]:
        stt_data = await stt(request)
        transcript = str(stt_data.get("text", "")).strip()
        if not transcript:
            return {"transcript": "", "response_text": "Nao consegui entender o audio.", "audio_base64": None}
        result = await _run_interaction(InteractRequest(user_id=user_id, transcript=transcript, room=room))
        result["transcript"] = transcript
        audio_b64: Optional[str] = None
        if speak and runtime.slave_power.base_url:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    tts_resp = await client.post(
                        f"{runtime.slave_power.base_url}/api/tts",
                        json={"text": result["response_text"]},
                        headers=runtime.slave_power.auth_headers,
                    )
                    if tts_resp.status_code == 200:
                        audio_b64 = base64.b64encode(tts_resp.content).decode("ascii")
            except Exception as exc:
                logger.warning("Falha opcional no TTS: %s", exc)
        result["audio_base64"] = audio_b64
        return result

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
