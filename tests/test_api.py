"""Testes de integracao da API FastAPI e canal WebSocket v2."""

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cortex_core.config import CortexSettings  # noqa: E402
from cortex_core.main import create_app  # noqa: E402


def test_health_and_status_endpoints() -> None:
    app = create_app(CortexSettings(database_url=None))
    with TestClient(app) as client:
        r_health = client.get("/health")
        assert r_health.status_code == 200
        assert r_health.json()["status"] == "ok"

        r_status = client.get("/api/cortex/status")
        assert r_status.status_code == 200
        assert any(t["name"] == "notify.send_external" for t in r_status.json()["tools"])


def test_fast_path_interaction_and_websocket_presence() -> None:
    app = create_app(CortexSettings(database_url=None))
    with TestClient(app) as client:
        with client.websocket_connect("/api/nodes/kiosk-banheiro/channel") as ws:
            ws.send_json(
                {
                    "type": "CORTEX_EVENT",
                    "node_id": "kiosk-banheiro",
                    "room": "banheiro",
                    "event": "PRESENCE_DETECTED",
                    "payload": {"person_hint": "will", "confidence": 0.95},
                }
            )

            resp = client.post(
                "/api/cortex/interact",
                json={
                    "user_id": "will",
                    "transcript": "Acender a luz do banheiro",
                    "node_id": "kiosk-banheiro",
                    "room": "banheiro",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["path"] == "fast_path"
            assert data["tool_used"] == "home.iot.light"
            assert data["target"]["node_id"] == "kiosk-banheiro"
            assert data["delivered_via_ws"] is True

            ws_msg = ws.receive_json()
            assert ws_msg["action"] == "CORTEX_SPEAK"
            assert "banheiro" in ws_msg["payload"]["text"].lower()
