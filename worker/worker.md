# C0rt3x Compute Worker (`worker`)

## 1. O que é
O módulo **`worker/`** é a API de inferência de IA e voz do nó **C0rt3x Compute** (`cortex-compute`, IP Tailnet `100.122.5.99`), projetada para aproveitar a GPU **AMD Radeon RX 7600 (8 GB VRAM, ROCm)** e a CPU Ryzen 5 3600 (12 threads, 15 GB RAM) do PC secundário sem sobrecarregar o Domus Server 24/7.

---

## 2. Componentes da Stack (`worker/compose.yaml`)
- **`cortex_ollama` (`ollama/ollama:rocm`):**
  - Acesso direto a `/dev/kfd` e `/dev/dri` com `HSA_OVERRIDE_GFX_VERSION=11.0.0` e `OLLAMA_KEEP_ALIVE=10m`.
  - Porta `127.0.0.1:11434` (loopback apenas) e rede interna `cortex_worker_net`.
  - Modelos instalados: `qwen2.5:7b` (chat/raciocínio) e `nomic-embed-text` (embeddings 768-d).
- **`cortex_worker` (`domus-cortex-worker:latest`):**
  - FastAPI rodando como usuário sem privilégios (`worker`), `mem_limit: 2g`, `no-new-privileges:true`.
  - Exposto exclusivamente no IP Tailscale `${WORKER_TAILSCALE_IP}:8090`.
  - Inclui `ffmpeg`, `faster-whisper` (`base`, int8) e `piper-tts` (`pt_BR-faber-medium`) com cache persistente em `./voice_models:/app/voice_models`.

---

## 3. Endpoints da API (`:8090`)
Todos os endpoints exigem `Authorization: Bearer <WORKER_API_TOKEN>` (validado em tempo constante via `hmac.compare_digest`):
- `GET /health` — verifica disponibilidade do `ollama` local e retorna modelo ativo.
- `POST /api/infer` — monta histórico (`SYSTEM_PROMPT`, memórias semânticas e turnos recentes) e chama `POST /api/chat` no Ollama.
- `POST /api/embed` — gera vetor de embedding via `POST /api/embed` (`nomic-embed-text`).
- `POST /api/stt` — recebe áudio bruto (`.webm`, `.ogg`, `.wav`), decodifica com `ffmpeg` para PCM float32 16 kHz mono e transcreve em português com `faster-whisper`.
- `POST /api/tts` — sintetiza texto em `audio/wav` via `PiperVoice.synthesize_wav`.

---

## 4. Regras Operacionais
1. Nunca expor a porta `8090` ou `11434` em `0.0.0.0` na rede pública/Wi-Fi.
2. O diretório `./voice_models` no host deve permitir leitura/escrita ao usuário `worker` do container.
3. O PC Gamer opera em **modo passivo via Tailnet**: quando ligado, atende ao Slow-Path, embeddings e voz; quando desligado, o `cortex_core` degrada graciosamente.
