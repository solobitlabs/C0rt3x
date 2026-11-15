"""Orquestrador de energia (Wake-on-LAN S3 e auto-sleep) do PC Gamer Slave."""

import asyncio
from enum import Enum
import logging
import socket
import time
from typing import Awaitable, Callable, Optional

import httpx

logger = logging.getLogger("cortex.slave_power")


class SlaveState(str, Enum):
    """Estados operacionais do worker GPU."""

    UNCONFIGURED = "UNCONFIGURED"
    SLEEPING_S3 = "SLEEPING_S3"
    WAKING_WOL = "WAKING_WOL"
    ONLINE_IDLE = "ONLINE_IDLE"
    BUSY_INFERENCE = "BUSY_INFERENCE"


def build_magic_packet(mac_address: str) -> bytes:
    """Constroi um Magic Packet Wake-on-LAN padrao (102 bytes)."""
    cleaned = mac_address.strip().replace(":", "").replace("-", "").upper()
    if len(cleaned) != 12:
        raise ValueError(f"MAC address invalido para WoL: {mac_address}")
    mac_bytes = bytes.fromhex(cleaned)
    return b"\xff" * 6 + mac_bytes * 16


def send_udp_magic_packet(
    mac_address: str,
    broadcast_ip: str = "255.255.255.255",
    port: int = 9,
) -> None:
    """Envia pacote UDP Wake-on-LAN na rede local."""
    packet = build_magic_packet(mac_address)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast_ip, port))


class SlavePowerManager:
    """Controla despertar sob demanda (S3 -> WoL) e suspensao por ociosidade."""

    def __init__(
        self,
        slave_mac: str,
        slave_host: str,
        slave_port: int = 8090,
        broadcast_ip: str = "255.255.255.255",
        wol_port: int = 9,
        idle_timeout_seconds: int = 600,
        wake_timeout_seconds: float = 12.0,
        poll_interval_seconds: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
        wol_sender: Optional[Callable[[str, str, int], None]] = None,
        health_probe: Optional[Callable[[str], Awaitable[bool]]] = None,
        sleep_trigger: Optional[Callable[[str], Awaitable[bool]]] = None,
    ) -> None:
        self._mac = slave_mac.strip()
        self._host = slave_host.strip()
        self._port = slave_port
        self._broadcast_ip = broadcast_ip
        self._wol_port = wol_port
        self._idle_timeout = idle_timeout_seconds
        self._wake_timeout = wake_timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._clock = clock

        self._wol_sender = wol_sender or send_udp_magic_packet
        self._health_probe = health_probe or self._default_health_probe
        self._sleep_trigger = sleep_trigger or self._default_sleep_trigger

        self._state = SlaveState.SLEEPING_S3 if (self._mac and self._host) else SlaveState.UNCONFIGURED
        self._last_activity_at = self._clock()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> SlaveState:
        return self._state

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    async def _default_health_probe(self, url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                resp = await client.get(f"{url}/health")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def _default_sleep_trigger(self, url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.post(f"{url}/system/sleep")
                return resp.status_code in (200, 202, 204)
        except httpx.HTTPError:
            return False

    async def ensure_online(self) -> bool:
        """Garante que o PC Gamer esteja acordado para inferencia."""
        if self._state == SlaveState.UNCONFIGURED:
            return False

        async with self._lock:
            if await self._health_probe(self.base_url):
                self._state = SlaveState.ONLINE_IDLE
                self._last_activity_at = self._clock()
                return True

            self._state = SlaveState.WAKING_WOL
            logger.info("Enviando Magic Packet WoL para o PC Gamer Slave (%s)", self._mac)
            self._wol_sender(self._mac, self._broadcast_ip, self._wol_port)

            deadline = self._clock() + self._wake_timeout
            while self._clock() < deadline:
                if await self._health_probe(self.base_url):
                    self._state = SlaveState.ONLINE_IDLE
                    self._last_activity_at = self._clock()
                    logger.info("PC Gamer Slave online e pronto para inferencia.")
                    return True
                await asyncio.sleep(self._poll_interval)

            self._state = SlaveState.SLEEPING_S3
            logger.warning("Timeout aguardando despertar do PC Gamer Slave.")
            return False

    def mark_busy(self) -> None:
        if self._state != SlaveState.UNCONFIGURED:
            self._state = SlaveState.BUSY_INFERENCE
            self._last_activity_at = self._clock()

    def mark_idle(self) -> None:
        if self._state != SlaveState.UNCONFIGURED:
            self._state = SlaveState.ONLINE_IDLE
            self._last_activity_at = self._clock()

    async def sleep_if_idle(self) -> bool:
        """Coloca o PC Gamer em suspensao S3 se o tempo de ociosidade foi atingido."""
        if self._state != SlaveState.ONLINE_IDLE:
            return False

        elapsed = self._clock() - self._last_activity_at
        if elapsed < self._idle_timeout:
            return False

        async with self._lock:
            if self._state != SlaveState.ONLINE_IDLE:
                return False
            if await self._sleep_trigger(self.base_url):
                self._state = SlaveState.SLEEPING_S3
                logger.info("PC Gamer Slave colocado em suspensao S3 apos %.0fs ocioso.", elapsed)
                return True
        return False

    def status_snapshot(self) -> dict[str, object]:
        return {
            "state": self._state.value,
            "configured": self._state != SlaveState.UNCONFIGURED,
            "idle_timeout_seconds": self._idle_timeout,
            "seconds_since_activity": round(max(0.0, self._clock() - self._last_activity_at), 1),
        }
