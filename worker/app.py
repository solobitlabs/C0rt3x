"""Worker de inferencia GPU (C0rt3x Compute) rodando no PC Gamer Slave."""

import hmac
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
import httpx
from pydantic import BaseModel, Field

logging.basicConfig(
    level=os.environ.get("WORKER_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cortex.worker")

OLLAMA_URL = os.environ.get("WORKER_OLLAMA_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("WORKER_OLLAMA_MODEL", "qwen2.5:7b")
WORKER_API_TOKEN = os.environ.get("WORKER_API_TOKEN", "").strip()

SYSTEM_PROMPT = (
    "Voce e o C0rt3x, o assistente residencial inteligente local da SoloBit Labs. "
    "Responda em portugues do Brasil de forma natural, clara, objetiva e util. "
    "Nunca invente dados que nao estejam no contexto ou memorias fornecidas."
)


class InferRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)
    recent_turns: List[Dict[str, str]] = Field(default_factory=list)
    memories: List[str] = Field(default_factory=list)
    tools: List[Dict[str, str]] = Field(default_factory=list)


def verify_bearer_token(authorization: Optional[str] = Header(default=None)) -> None:
    """Valida token Bearer em tempo constante quando WORKER_API_TOKEN esta configurado."""
    if not WORKER_API_TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token ausente")
    provided = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(provided, WORKER_API_TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido")


def build_messages(req: InferRequest) -> List[Dict[str, str]]:
    """Monta historico de mensagens para o Ollama injetando memorias semanticas."""
    system_parts = [SYSTEM_PROMPT]
    if req.memories:
        mem_block = "\n".join(f"- {m}" for m in req.memories[:5])
        system_parts.append(f"Memorias relevantes sobre o morador:\n{mem_block}")

    messages: List[Dict[str, str]] = [{"role": "system", "content": "\n\n".join(system_parts)}]
    for turn in req.recent_turns[-8:]:
        role = turn.get("role", "user")
        if role not in ("user", "assistant"):
            role = "user"
        text = str(turn.get("text", "")).strip()
        if text:
            messages.append({"role": role, "content": text})

    if not messages or messages[-1]["role"] != "user" or messages[-1]["content"] != req.prompt.strip():
        messages.append({"role": "user", "content": req.prompt.strip()})
    return messages


app = FastAPI(title="Domus C0rt3x Compute Worker", version="0.1.0")


@app.get("/health")
async def health(_: None = Depends(verify_bearer_token)) -> Dict[str, Any]:
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            ollama_ok = r.status_code == 200
    except httpx.HTTPError:
        ollama_ok = False
    return {"status": "ok", "model": OLLAMA_MODEL, "ollama_reachable": ollama_ok}


@app.post("/api/infer")
async def infer(req: InferRequest, _: None = Depends(verify_bearer_token)) -> Dict[str, Any]:
    messages = build_messages(req)
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            text = str(data.get("message", {}).get("content", "")).strip()
            return {"text": text or "Certo.", "model": OLLAMA_MODEL}
    except httpx.HTTPError as exc:
        logger.error("Erro ao consultar Ollama: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Falha na inferencia local do Ollama",
        ) from exc
