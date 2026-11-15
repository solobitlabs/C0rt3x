"""Domus Cortex Edge Daemon (domus-cortex-daemon).

Collects host CPU, RAM, disk, top processes, AMD ROCm GPU telemetry (sysfs),
Docker containers, and Ollama model status from cortex-compute and pushes
snapshots to Domus Dashboard over Tailnet HTTPS.
"""

from __future__ import annotations

import logging
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import psutil

if Path("/host/proc").exists():
    psutil.PROCFS_PATH = "/host/proc"

logging.basicConfig(
    level=os.getenv("DAEMON_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] domus-cortex-daemon: %(message)s",
)
logger = logging.getLogger("domus-cortex-daemon")

SYS_DRM_PATH = Path(os.getenv("DAEMON_SYS_DRM_PATH", "/host/sys/class/drm" if Path("/host/sys/class/drm").exists() else "/sys/class/drm"))
DOCKER_SOCK_PATH = os.getenv("DAEMON_DOCKER_SOCK", "/var/run/docker.sock")
OLLAMA_URL = os.getenv("DAEMON_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
DASHBOARD_URL = os.getenv(
    "DOMUS_DASHBOARD_URL",
    "https://stats.domus.solobit.com.br/api/compute/telemetry",
).rstrip("/")
TELEMETRY_TOKEN = os.getenv("COMPUTE_TELEMETRY_TOKEN", "").strip()
INTERVAL_SECONDS = max(3, int(os.getenv("DAEMON_INTERVAL_SECONDS", "10")))
NODE_ID = os.getenv("DAEMON_NODE_ID", "cortex-compute")
TAILSCALE_IP = os.getenv("WORKER_TAILSCALE_IP", "100.122.5.99")


def _read_int_file(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def collect_amd_gpu_metrics(drm_root: Path = SYS_DRM_PATH) -> dict[str, Any]:
    """Read AMD GPU busy %, VRAM usage, temperature, and power from sysfs."""
    result: dict[str, Any] = {
        "available": False,
        "name": "AMD Radeon RX 7600",
        "busy_percent": 0.0,
        "vram_used_mb": 0.0,
        "vram_total_mb": 0.0,
        "vram_percent": 0.0,
        "temp_c": None,
        "power_watts": None,
    }
    if not drm_root.exists():
        return result

    for card_dir in sorted(drm_root.glob("card[0-9]*")):
        if "-" in card_dir.name:
            continue
        dev = card_dir / "device"
        busy_path = dev / "gpu_busy_percent"
        vram_used_path = dev / "mem_info_vram_used"
        vram_total_path = dev / "mem_info_vram_total"
        if not busy_path.exists() and not vram_total_path.exists():
            continue

        result["available"] = True
        busy = _read_int_file(busy_path)
        if busy is not None:
            result["busy_percent"] = float(busy)

        vram_used = _read_int_file(vram_used_path)
        vram_total = _read_int_file(vram_total_path)
        if vram_used is not None and vram_total and vram_total > 0:
            result["vram_used_mb"] = round(vram_used / (1024 * 1024), 1)
            result["vram_total_mb"] = round(vram_total / (1024 * 1024), 1)
            result["vram_percent"] = round((vram_used / vram_total) * 100.0, 1)

        hwmon_root = dev / "hwmon"
        if hwmon_root.exists():
            for hw in sorted(hwmon_root.glob("hwmon*")):
                temp_raw = _read_int_file(hw / "temp1_input")
                if temp_raw is not None:
                    result["temp_c"] = round(temp_raw / 1000.0, 1)
                power_raw = _read_int_file(hw / "power1_average")
                if power_raw is not None:
                    result["power_watts"] = round(power_raw / 1_000_000.0, 1)
                break
        break

    return result


def collect_processes_summary(limit: int = 8) -> dict[str, Any]:
    """Collect host process count and top CPU / RAM consumers."""
    procs: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info", "status"]):
        try:
            info = proc.info
            mem_info = info.get("memory_info")
            rss_mb = round((mem_info.rss / (1024 * 1024)), 1) if mem_info else 0.0
            procs.append(
                {
                    "pid": info["pid"],
                    "name": info.get("name") or "unknown",
                    "cpu_percent": round(float(info.get("cpu_percent") or 0.0), 1),
                    "memory_mb": rss_mb,
                    "status": info.get("status") or "",
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    top_cpu = sorted(procs, key=lambda p: p["cpu_percent"], reverse=True)[:limit]
    top_memory = sorted(procs, key=lambda p: p["memory_mb"], reverse=True)[:limit]
    return {
        "total_count": len(procs),
        "top_cpu": top_cpu,
        "top_memory": top_memory,
    }


def collect_docker_containers(sock_path: str = DOCKER_SOCK_PATH) -> list[dict[str, Any]]:
    """Query local Docker Engine via Unix socket for container states."""
    if not Path(sock_path).exists():
        return []
    try:
        transport = httpx.HTTPTransport(uds=sock_path)
        with httpx.Client(transport=transport, base_url="http://docker", timeout=3.0) as client:
            resp = client.get("/containers/json?all=1")
            resp.raise_for_status()
            items = resp.json()
    except Exception as exc:
        logger.debug("Docker socket query failed: %s", exc)
        return []

    containers: list[dict[str, Any]] = []
    for item in items:
        names = item.get("Names") or []
        name = names[0].lstrip("/") if names else item.get("Id", "")[:12]
        containers.append(
            {
                "name": name,
                "image": item.get("Image", ""),
                "state": item.get("State", "unknown"),
                "status": item.get("Status", ""),
            }
        )
    return containers


def collect_ollama_status(ollama_url: str = OLLAMA_URL) -> dict[str, Any]:
    """Query local Ollama API for running (loaded in VRAM) and available models."""
    status: dict[str, Any] = {
        "reachable": False,
        "running_models": [],
        "available_models": [],
    }
    try:
        with httpx.Client(timeout=2.5) as client:
            ps_resp = client.get(f"{ollama_url}/api/ps")
            if ps_resp.status_code == 200:
                status["reachable"] = True
                models = ps_resp.json().get("models") or []
                status["running_models"] = [
                    {
                        "name": m.get("name", ""),
                        "size_vram_mb": round((m.get("size_vram") or 0) / (1024 * 1024), 1),
                    }
                    for m in models
                ]
            tags_resp = client.get(f"{ollama_url}/api/tags")
            if tags_resp.status_code == 200:
                status["reachable"] = True
                models = tags_resp.json().get("models") or []
                status["available_models"] = [m.get("name", "") for m in models]
    except Exception as exc:
        logger.debug("Ollama query failed: %s", exc)
    return status


def build_telemetry_snapshot() -> dict[str, Any]:
    """Build complete edge telemetry payload for Domus Dashboard."""
    cpu_pct = round(float(psutil.cpu_percent(interval=None)), 1)
    vmem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    load_avg = list(os.getloadavg()) if hasattr(os, "getloadavg") else [0.0, 0.0, 0.0]

    cpu_temp_c: float | None = None
    try:
        temps = psutil.sensors_temperatures() or {}
        for key in ("k10temp", "coretemp", "zenpower"):
            if key in temps and temps[key]:
                cpu_temp_c = round(float(temps[key][0].current), 1)
                break
    except Exception:
        pass

    return {
        "node_id": NODE_ID,
        "hostname": socket.gethostname(),
        "tailscale_ip": TAILSCALE_IP,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        "cpu": {
            "percent": cpu_pct,
            "cores_logical": psutil.cpu_count(logical=True) or 0,
            "cores_physical": psutil.cpu_count(logical=False) or 0,
            "load_avg": [round(x, 2) for x in load_avg],
            "temp_c": cpu_temp_c,
        },
        "memory": {
            "percent": round(float(vmem.percent), 1),
            "used_gb": round(vmem.used / (1024**3), 2),
            "total_gb": round(vmem.total / (1024**3), 2),
            "swap_percent": round(float(swap.percent), 1),
        },
        "disk": {
            "percent": round(float(disk.percent), 1),
            "used_gb": round(disk.used / (1024**3), 1),
            "total_gb": round(disk.total / (1024**3), 1),
        },
        "gpu": collect_amd_gpu_metrics(),
        "processes": collect_processes_summary(),
        "containers": collect_docker_containers(),
        "ollama": collect_ollama_status(),
    }


def push_snapshot(client: httpx.Client, snapshot: dict[str, Any]) -> bool:
    """Send telemetry snapshot to Domus Dashboard."""
    headers: dict[str, str] = {}
    if TELEMETRY_TOKEN:
        headers["Authorization"] = f"Bearer {TELEMETRY_TOKEN}"
    try:
        resp = client.post(DASHBOARD_URL, json=snapshot, headers=headers)
        if resp.status_code < 300:
            return True
        logger.warning("Dashboard returned HTTP %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("Failed to push telemetry to %s: %s", DASHBOARD_URL, exc)
    return False


def main() -> None:
    logger.info(
        "Starting domus-cortex-daemon (node=%s, interval=%ss, target=%s)",
        NODE_ID,
        INTERVAL_SECONDS,
        DASHBOARD_URL,
    )
    # Prime psutil CPU percent counters
    psutil.cpu_percent(interval=None)
    for proc in psutil.process_iter(["cpu_percent"]):
        pass

    with httpx.Client(timeout=8.0) as client:
        while True:
            snapshot = build_telemetry_snapshot()
            push_snapshot(client, snapshot)
            time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
