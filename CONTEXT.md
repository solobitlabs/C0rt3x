# 🧠 Domus C0rt3x — Contexto Técnico & Guia de Desenvolvimento

Este arquivo mantém o estado vivo da implementação do **C0rt3x Core** para desenvolvedores e agentes de IA.

---

## 1. Princípios Inegociáveis de Engenharia
1. **Privacidade & Zero Nuvem:** Nenhum dado de voz, presença, câmera, despensa ou financeiro é enviado para LLMs externos.
2. **Segurança & Isolamento:**
   - O `C0rt3x Core` roda exclusivamente na rede privada `domus_internal` (+ `domus_db` e `notify_bus`).
   - Segredos residem apenas em variáveis de ambiente (`.env` com `chmod 600` fora do Git); logs nunca imprimem tokens ou payloads sensíveis de áudio/imagem.
   - A câmera dos nodes nunca grava vídeo em disco; apenas eventos JSON de presença (`PRESENCE_DETECTED`) chegam ao Core.
3. **Eficiência Energética & Baixa Latência:**
   - *Fast-Path* determinístico na CPU do Domus (`< 50ms`) para comandos de rotina (luz, mídia, clima).
   - *Slow-Path* acorda a GPU do PC Gamer Slave via **Wake-on-LAN (S3 Sleep)** em `2–3s` e hiberna após `600s` de ociosidade.
4. **Commits Atômicos & Testes Contínuos:** Toda alteração deve manter os testes (`pytest`) 100% verdes antes do commit.

---

## 2. Estrutura do Repositório (`solobitlabs/C0rt3x`)

```text
/srv/domus/apps/domus-cortex/
├── CONTEXT.md                    # Este guia vivo de contexto
├── domus-cortex.md               # Arquitetura detalhada, atores e diretrizes do C0rt3x
├── README.md                     # Visão geral e índice do projeto
├── daemon/                       # domus-cortex-daemon (telemetria Edge + GPU RX 7600)
│   └── daemon.md                 # Documentação do daemon de telemetria
├── worker/                       # Stack C0rt3x Compute (Ollama ROCm + Inferência + Voz)
│   └── worker.md                 # Documentação do worker GPU/STT/TTS
├── requirements.txt              # Dependências de produção (FastAPI, Pydantic, httpx, asyncpg)
├── requirements-dev.txt          # Dependências de teste (pytest, pytest-asyncio)
├── docs/                         # Documentação técnica, ADRs e GitHub Pages (docs/index.html)
├── src/cortex_core/
│   ├── config.py                 # Configurações tipadas via Pydantic BaseSettings
│   ├── core/
│   │   ├── spatial_engine.py     # Grafo de cômodos e pontuação Follow-Me (TTL)
│   │   ├── session_manager.py    # Sessões centradas no morador e janela expect_reply
│   │   ├── slave_power.py        # Máquina de estados WoL S3 e reaper de ociosidade
│   │   ├── cognitive_router.py   # Fast-Path (CPU) vs Slow-Path (GPU Slave)
│   │   └── memory_engine.py      # Working, Episodic (SQL) e Semantic (pgvector/fallback)
│   ├── tools/
│   │   ├── registry.py           # Registro seguro de ferramentas (MCP/Tools)
│   │   └── notify_tool.py        # Cliente Apprise via notify_bus
│   └── main.py                   # Gateway FastAPI + Canal WebSocket v2
└── tests/                        # Suíte de testes unitários e de integração
```

---

## 3. Status da Implementação (Fase 1)
- [x] Documentação arquitetural, ADRs e GitHub Pages (`https://solobit.com.br/C0rt3x/`)
- [x] `config.py` — Configuração tipada e sanitizada
- [x] `spatial_engine.py` — Motor espacial Follow-Me
- [x] `session_manager.py` — Gerenciador de sessões por usuário
- [x] `slave_power.py` — Orquestrador Wake-on-LAN S3 e modo passivo autenticado via Tailnet (`CORTEX_SLAVE_API_TOKEN`)
- [x] `cognitive_router.py` & `tools/` — Roteador híbrido + Tool Registry
- [x] `memory_engine.py` — Memória em 3 camadas no `postgres-domus`
- [x] `main.py` — API FastAPI + WebSocket Full-Duplex v2 + Deploy Docker no Domus
- [x] `worker/` — Stack `C0rt3x Compute` (`ollama/ollama:rocm` + API autenticada `:8090`, `qwen2.5:7b`, `nomic-embed-text`, `faster-whisper`, `piper-tts`)
- [x] `daemon/` — `domus-cortex-daemon` enviando telemetria ao vivo (CPU, RAM, RX 7600, processos, Ollama) para o Domus Dashboard
- [x] `domus.tools` & Memória Semântica — Tools Fast-Path reais (`server`, `compute`, `dns`, `notify`) e embeddings no `postgres-domus`
- [ ] Base de Edge Nodes, Periféricos, Descoberta & Manutenção IoT (ver [docs/CONTINUITY_PLAN.md](docs/CONTINUITY_PLAN.md))
