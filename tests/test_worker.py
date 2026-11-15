"""Testes unitarios para o worker de inferencia GPU (autenticacao e prompt)."""

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

WORKER_PATH = Path(__file__).resolve().parents[1] / "worker" / "app.py"
spec = importlib.util.spec_from_file_location("cortex_worker_app", WORKER_PATH)
assert spec and spec.loader
worker_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker_mod)


def test_worker_auth_rejects_missing_or_wrong_token(monkeypatch) -> None:
    monkeypatch.setattr(worker_mod, "WORKER_API_TOKEN", "segredo-123")
    client = TestClient(worker_mod.app)

    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"Authorization": "Bearer errado"}).status_code == 401
    assert client.get("/health", headers={"Authorization": "Bearer segredo-123"}).status_code == 200


def test_worker_build_messages_injects_memories_and_turns() -> None:
    req = worker_mod.InferRequest(
        prompt="O que fazer pro jantar?",
        recent_turns=[{"role": "user", "text": "Oi Cortex"}],
        memories=["Will gosta de risoto"],
    )
    msgs = worker_mod.build_messages(req)
    assert msgs[0]["role"] == "system"
    assert "Will gosta de risoto" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "Oi Cortex"}
    assert msgs[-1] == {"role": "user", "content": "O que fazer pro jantar?"}
