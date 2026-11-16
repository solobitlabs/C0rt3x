"""Worker de inferencia GPU (C0rt3x Compute) rodando no PC Gamer Slave."""

import hmac
import io
import logging
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Dict, List, Optional
import wave

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
import httpx
from pydantic import BaseModel, Field

logging.basicConfig(
    level=os.environ.get("WORKER_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cortex.worker")

OLLAMA_URL = os.environ.get("WORKER_OLLAMA_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("WORKER_OLLAMA_MODEL", "qwen2.5:7b")
EMBED_MODEL = os.environ.get("WORKER_EMBED_MODEL", "nomic-embed-text")
WHISPER_MODEL = os.environ.get("WORKER_WHISPER_MODEL", "base")
VOICE_MODELS_DIR = Path(os.environ.get("WORKER_VOICE_MODELS_DIR", "/app/voice_models"))
PIPER_VOICE_NAME = os.environ.get("WORKER_PIPER_VOICE", "pt_BR-faber-medium")
WORKER_API_TOKEN = os.environ.get("WORKER_API_TOKEN", "").strip()

_whisper_instance: Any = None
_piper_instance: Any = None

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


class EmbedRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


class TtsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


def _get_whisper_model() -> Any:
    global _whisper_instance
    if _whisper_instance is None:
        from faster_whisper import WhisperModel

        VOICE_MODELS_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Carregando Faster-Whisper (%s)...", WHISPER_MODEL)
        _whisper_instance = WhisperModel(
            WHISPER_MODEL,
            device="cpu",
            compute_type="int8",
            download_root=str(VOICE_MODELS_DIR),
        )
    return _whisper_instance


def _ensure_piper_model_files() -> Path:
    VOICE_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    onnx_path = VOICE_MODELS_DIR / f"{PIPER_VOICE_NAME}.onnx"
    json_path = VOICE_MODELS_DIR / f"{PIPER_VOICE_NAME}.onnx.json"
    if not onnx_path.exists() or not json_path.exists():
        # Ex: pt_BR-faber-medium -> pt/pt_BR/faber/medium/
        parts = PIPER_VOICE_NAME.split("-")
        lang_country = parts[0]
        lang = lang_country.split("_")[0]
        speaker = parts[1] if len(parts) > 1 else "faber"
        quality = parts[2] if len(parts) > 2 else "medium"
        base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang}/{lang_country}/{speaker}/{quality}/{PIPER_VOICE_NAME}"
        logger.info("Baixando voz Piper PT-BR: %s", PIPER_VOICE_NAME)
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            if not onnx_path.exists():
                r1 = client.get(f"{base}.onnx")
                r1.raise_for_status()
                onnx_path.write_bytes(r1.content)
            if not json_path.exists():
                r2 = client.get(f"{base}.onnx.json")
                r2.raise_for_status()
                json_path.write_bytes(r2.content)
    return onnx_path


def _get_piper_voice() -> Any:
    global _piper_instance
    if _piper_instance is None:
        from piper.voice import PiperVoice

        onnx_path = _ensure_piper_model_files()
        logger.info("Carregando Piper TTS (%s)...", onnx_path.name)
        _piper_instance = PiperVoice.load(str(onnx_path))
    return _piper_instance


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


@app.post("/api/embed")
async def embed(req: EmbedRequest, _: None = Depends(verify_bearer_token)) -> Dict[str, Any]:
    """Gera vetor de embedding via Ollama para memoria semantica."""
    payload = {"model": EMBED_MODEL, "input": req.text}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{OLLAMA_URL}/api/embed", json=payload)
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings") or []
            vec = embeddings[0] if embeddings else data.get("embedding") or []
            return {"embedding": vec, "model": EMBED_MODEL}
    except httpx.HTTPError as exc:
        logger.error("Erro ao gerar embedding no Ollama: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Falha ao gerar embedding no Ollama",
        ) from exc


@app.post("/api/stt")
async def speech_to_text(
    request: Request,
    _: None = Depends(verify_bearer_token),
) -> Dict[str, Any]:
    """Transcreve audio em portugues usando Faster-Whisper."""
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Audio vazio")
    ctype = request.headers.get("content-type", "audio/webm").lower()
    suffix = ".wav" if "wav" in ctype else (".ogg" if "ogg" in ctype else ".webm")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(raw)
        tmp.flush()
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", tmp.name, "-ar", "16000", "-ac", "1", "-f", "f32le", "-"],
            capture_output=True,
            check=True,
        )
        import numpy as np

        audio_np = np.frombuffer(proc.stdout, dtype=np.float32)
        model = _get_whisper_model()
        segments, info = model.transcribe(audio_np, language="pt", beam_size=5, vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return {
            "text": text,
            "language": getattr(info, "language", "pt"),
            "duration": round(float(getattr(info, "duration", 0.0) or 0.0), 2),
        }


@app.post("/api/tts")
async def text_to_speech(
    req: TtsRequest,
    _: None = Depends(verify_bearer_token),
) -> Response:
    """Sintetiza fala em portugues (audio/wav) usando Piper TTS."""
    voice = _get_piper_voice()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        voice.synthesize_wav(req.text.strip(), wav_file)
    return Response(content=buf.getvalue(), media_type="audio/wav")
