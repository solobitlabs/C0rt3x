"""Testes de integracao para memoria semantica via /api/cortex/interact e /api/cortex/memories."""

from fastapi.testclient import TestClient

from cortex_core.config import CortexSettings
from cortex_core.main import create_app


def test_save_and_list_semantic_memory_via_api() -> None:
    settings = CortexSettings(database_url=None, apprise_url="")
    app = create_app(settings)
    with TestClient(app) as client:
        r_save = client.post(
            "/api/cortex/interact",
            json={
                "user_id": "will",
                "transcript": "Lembre que eu prefiro cafe sem acucar",
                "room": "cozinha",
            },
        )
        assert r_save.status_code == 200
        body = r_save.json()
        assert body["path"] == "fast_path"
        assert body["tool_used"] == "memory.save"
        assert "cafe sem acucar" in body["response_text"]

        r_list = client.get("/api/cortex/memories?user_id=will")
        assert r_list.status_code == 200
        mems = r_list.json()["memories"]
        assert any("cafe sem acucar" in m for m in mems)
