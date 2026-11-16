"""Ferramentas Fast-Path para consultar telemetria real do Domus Server e Edge Compute."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("cortex.tools.domus")


class DomusTelemetryClient:
    """Consulta o Domus Dashboard na rede interna para respostas instantaneas."""

    def __init__(self, dashboard_url: Optional[str] = None) -> None:
        self._url = (
            dashboard_url
            or os.getenv("CORTEX_DASHBOARD_URL", "http://domus_dashboard:8000")
        ).rstrip("/")

    async def _fetch_stats(self) -> Optional[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(f"{self._url}/api/stats")
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("Falha ao consultar Domus Dashboard (%s): %s", self._url, exc)
            return None

    async def server_summary(self) -> str:
        """Retorna resumo em texto do Domus Server (Master 24/7)."""
        data = await self._fetch_stats()
        if not data:
            return "Nao consegui consultar as metricas do Domus Server agora."

        host = data.get("host") or {}
        mem = host.get("memory") or {}
        disk = host.get("disk") or {}
        containers = data.get("containers") or {}
        cpu_pct = host.get("cpu_percent", 0)
        ram_pct = mem.get("percent", 0)
        used_gb = round((mem.get("used_mb", 0) or 0) / 1024, 1)
        total_gb = round((mem.get("total_mb", 0) or 0) / 1024, 1)
        running = containers.get("running", 0)
        total = containers.get("total", 0)
        disk_pct = disk.get("percent", 0)

        return (
            f"Domus Server online: CPU em {cpu_pct}%, RAM em {ram_pct}% "
            f"({used_gb}/{total_gb} GB), disco em {disk_pct}% e "
            f"{running} de {total} containers em execucao."
        )

    async def compute_summary(self) -> str:
        """Retorna resumo em texto do no Edge GPU (cortex-compute)."""
        data = await self._fetch_stats()
        if not data:
            return "Nao consegui consultar o status do C0rt3x Compute agora."

        nodes = data.get("compute_nodes") or {}
        node = nodes.get("cortex-compute") or (next(iter(nodes.values()), None) if nodes else None)
        if not node:
            return "O no C0rt3x Compute ainda nao enviou telemetria."

        if not node.get("online"):
            ago = node.get("last_seen_seconds_ago", "?")
            return f"O C0rt3x Compute esta offline (ultimo sinal ha {ago}s)."

        cpu = node.get("cpu") or {}
        mem = node.get("memory") or {}
        gpu = node.get("gpu") or {}
        ollama = node.get("ollama") or {}
        running_models = ollama.get("running_models") or []
        model_label = running_models[0]["name"] if running_models else "nenhum modelo carregado"

        vram_used_gb = round((gpu.get("vram_used_mb", 0) or 0) / 1024, 2)
        vram_total_gb = round((gpu.get("vram_total_mb", 0) or 0) / 1024, 1)
        temp_c = gpu.get("temp_c")
        temp_str = f", temperatura de {temp_c} °C" if temp_c is not None else ""

        return (
            f"C0rt3x Compute online: CPU em {cpu.get('percent', 0)}%, "
            f"RAM em {mem.get('used_gb', 0)}/{mem.get('total_gb', 0)} GB, "
            f"RX 7600 em {gpu.get('busy_percent', 0)}% com VRAM {vram_used_gb}/{vram_total_gb} GB"
            f"{temp_str} (Ollama: {model_label})."
        )

    async def dns_summary(self) -> str:
        """Retorna resumo de consultas e bloqueios do AdGuard DNS."""
        data = await self._fetch_stats()
        if not data or not data.get("dns"):
            return "Metricas do AdGuard DNS indisponiveis no momento."

        dns = data["dns"]
        queries = dns.get("queries_today", 0)
        blocked = dns.get("blocked_today", 0)
        pct = dns.get("blocked_percent", 0)
        return f"AdGuard DNS hoje: {queries} consultas totais e {blocked} bloqueios ({pct}%)."
