"""Roteador cognitivo de 2 velocidades: Fast-Path (CPU <50ms) vs Slow-Path (GPU)."""

from dataclasses import dataclass
import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

from cortex_core.core.slave_power import SlavePowerManager
from cortex_core.tools.registry import ToolRegistry

logger = logging.getLogger("cortex.router")


@dataclass(frozen=True)
class RouteDecision:
    """Resultado do processamento de uma intencao pelo CognitiveRouter."""

    path: str  # "fast_path" | "slow_path" | "degraded"
    response_text: str
    expect_reply_seconds: int = 0
    tool_used: Optional[str] = None


SlaveInferFn = Callable[[str, List[Dict[str, str]], List[str]], Awaitable[str]]


class CognitiveRouter:
    """Resolve comandos deterministicos na CPU e delega raciocinio complexo ao Slave GPU."""

    _LIGHT_RE = re.compile(r"\b(acend\w*|apag\w*|lig\w*|deslig\w*)\s+(?:a\s+)?luz(?:\s+d[aoe]\s+([\w\s]+))?", re.I)
    _PLAY_RE = re.compile(r"\b(?:reproduz\w*|to(?:c|qu)\w*)\s+(.+?)(?:\s+n[ao]\s+([\w]+))?$", re.I)
    _PAUSE_RE = re.compile(r"\b(paus\w*|par\w*\s+m[uú]sica)\b", re.I)
    _COMPUTE_RE = re.compile(r"\b(gpu|rx\s*7600|vram|cortex[\s-]*compute|pc\s*gamer|ollama)\b", re.I)
    _DNS_RE = re.compile(r"\b(adguard|dns|bloqueio\w*)\b", re.I)
    _SERVER_RE = re.compile(r"\b(servidor|domus\s*server|containers?|cpu|ram|temperatura)\b", re.I)
    _NOTIFY_RE = re.compile(r"\b(?:notifiqu\w*|avis\w*|mand\w*\s+(?:uma\s+)?notifica[cç][aã]o)\s+(?:que\s+)?(.+)$", re.I)

    def __init__(
        self,
        tool_registry: ToolRegistry,
        slave_power: SlavePowerManager,
        slave_infer_fn: Optional[SlaveInferFn] = None,
    ) -> None:
        self._tools = tool_registry
        self._slave = slave_power
        self._slave_infer_fn = slave_infer_fn or self._default_slave_infer

    async def _default_slave_infer(
        self,
        prompt: str,
        recent_turns: List[Dict[str, str]],
        memories: List[str],
    ) -> str:
        payload = {
            "prompt": prompt,
            "recent_turns": recent_turns,
            "memories": memories,
            "tools": self._tools.list_tools(),
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._slave.base_url}/api/infer",
                json=payload,
                headers=self._slave.auth_headers,
            )
            resp.raise_for_status()
            data = resp.json()
            return str(data.get("text") or "Certo.")

    async def route(
        self,
        transcript: str,
        room: str = "unknown",
        recent_turns: Optional[List[Dict[str, str]]] = None,
        memories: Optional[List[str]] = None,
    ) -> RouteDecision:
        """Executa Fast-Path deterministico ou acorda o Slave GPU para Slow-Path."""
        clean = transcript.strip()
        if not clean:
            return RouteDecision(
                path="fast_path",
                response_text="Nao consegui ouvir nenhum comando.",
                expect_reply_seconds=6,
            )

        # 1. Fast-Path: Controle de iluminacao
        if match := self._LIGHT_RE.search(clean):
            verb = match.group(1).lower()
            target_room = (match.group(2) or room).strip().lower()
            action = "off" if verb.startswith(("apag", "deslig")) else "on"
            if "home.iot.light" in {t["name"] for t in self._tools.list_tools()}:
                await self._tools.execute("home.iot.light", room=target_room, state=action)
            label = "desligada" if action == "off" else "ligada"
            return RouteDecision(
                path="fast_path",
                response_text=f"Luz de {target_room} {label}.",
                tool_used="home.iot.light",
            )

        # 2. Fast-Path: Pausa de midia
        if self._PAUSE_RE.search(clean):
            if "media.pause" in {t["name"] for t in self._tools.list_tools()}:
                await self._tools.execute("media.pause", zone=room)
            return RouteDecision(
                path="fast_path",
                response_text="Reproducao pausada.",
                tool_used="media.pause",
            )

        # 3. Fast-Path: Reproducao de midia por comando direto
        if match := self._PLAY_RE.search(clean):
            track = match.group(1).strip()
            zone = (match.group(2) or room).strip().lower()
            if "media.play" in {t["name"] for t in self._tools.list_tools()}:
                await self._tools.execute("media.play", query=track, zone=zone)
            return RouteDecision(
                path="fast_path",
                response_text=f"Certo, tocando {track} em {zone}.",
                tool_used="media.play",
            )

        registered = {t["name"] for t in self._tools.list_tools()}

        # 3b. Fast-Path: Telemetria do Edge GPU (cortex-compute)
        if self._COMPUTE_RE.search(clean) and "domus.stats.compute" in registered:
            summary = await self._tools.execute("domus.stats.compute")
            return RouteDecision(
                path="fast_path",
                response_text=str(summary),
                tool_used="domus.stats.compute",
            )

        # 3c. Fast-Path: Metricas AdGuard DNS
        if self._DNS_RE.search(clean) and "domus.stats.dns" in registered:
            summary = await self._tools.execute("domus.stats.dns")
            return RouteDecision(
                path="fast_path",
                response_text=str(summary),
                tool_used="domus.stats.dns",
            )

        # 3d. Fast-Path: Telemetria do Domus Server
        if self._SERVER_RE.search(clean) and "domus.stats.server" in registered:
            summary = await self._tools.execute("domus.stats.server")
            return RouteDecision(
                path="fast_path",
                response_text=str(summary),
                tool_used="domus.stats.server",
            )

        # 3e. Fast-Path: Notificacao via Apprise
        if (match := self._NOTIFY_RE.search(clean)) and "notify.send_external" in registered:
            msg = match.group(1).strip()
            ok = await self._tools.execute("notify.send_external", title="C0rt3x", body=msg)
            return RouteDecision(
                path="fast_path",
                response_text="Notificacao enviada pelo Apprise." if ok else "Falha ao enviar notificacao via Apprise.",
                tool_used="notify.send_external",
            )

        # 4. Slow-Path: Exige raciocinio aberto no PC Gamer Slave (GPU)
        online = await self._slave.ensure_online()
        if not online:
            return RouteDecision(
                path="degraded",
                response_text=(
                    "O modulo de IA GPU esta dormindo ou indisponivel no momento. "
                    "Comandos rapidos da casa continuam funcionando normalmente."
                ),
            )

        self._slave.mark_busy()
        try:
            answer = await self._slave_infer_fn(clean, recent_turns or [], memories or [])
            return RouteDecision(path="slow_path", response_text=answer)
        except Exception as exc:
            logger.warning("Erro durante inferencia no Slave GPU: %s", exc)
            return RouteDecision(
                path="degraded",
                response_text="Nao foi possivel concluir a consulta cognitiva no worker GPU.",
            )
        finally:
            self._slave.mark_idle()
