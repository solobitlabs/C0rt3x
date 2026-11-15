# 🧠 Domus C0rt3x

**Assistente Residencial Cognitivo 100% Local, Autônomo e Privado — O "Jarvis" da SoloBit Labs.**

> 🌐 **Dashboard Arquitetural Interativo (GitHub Pages):**  
> 👉 **[https://solobit.com.br/C0rt3x/](https://solobit.com.br/C0rt3x/)**  
> *(Contém diagramas interativos, simulador "Follow-Me", simulador do leitor de CD `/dev/sr0`, orçamento de memória e contrato WebSocket v2).*

---

## 🎯 Visão do Projeto

O **Domus C0rt3x** transforma uma infraestrutura doméstica modesta (**Domus Server**, ligado 24/7 com baixo consumo) em um cérebro residencial capaz de:

1. **Orquestrar IA Local Sob Demanda (Master/Slave):** Mantém o núcleo cognitivo (`C0rt3x Core`) sempre ativo no servidor central e acorda um **PC Gamer Slave com GPU dedicada** em **2–3 segundos via Wake-on-LAN (Suspensão S3)** apenas quando inferência pesada (LLM, STT, TTS neural ou visão) é necessária.
2. **Acompanhar o Morador entre Cômodos ("Follow-Me" Handoff):** A conversa pertence à pessoa (`session:{user_id}`), não ao aparelho. Você pode fazer uma pergunta ao tablet da cozinha, caminhar pela sala e ouvir/ver a resposta no espelho do banheiro — ou recebê-la via Tailnet/Telegram ao sair de casa.
3. **Interagir Proativamente com Hardware Físico (`/dev/sr0` + Sensores):** Ao inserir um CD ou DVD físico no drive do servidor, o C0rt3x identifica a mídia via TOC/MusicBrainz, reconhece quem está próximo, pergunta se deseja reproduzir e abre o microfone automaticamente sem exigir palavra de ativação repetida.
4. **Integrar Dados Reais da Residência com Zero Nuvem:** Cruza informações da despensa doméstica (**Minha Despensa**), finanças pessoais (**Carteira**), telemetria IoT (**AirPower / ThingsBoard / ESPHome**), calendários e áudio multi-ambiente (**Music Assistant + Navidrome**).

---

## 🏗️ Arquitetura em 3 Camadas Físicas

| Camada | Onde Roda | Estado Operacional | Responsabilidades |
| :--- | :--- | :--- | :--- |
| **1. C0rt3x Edge** | Tablets Kiosk, Celulares antigos, Domus TV, Domus Mobile, ESP32, Drive `/dev/sr0` | Sempre nos cômodos e bolso | Wake-word local (`"Cortex"`), detecção facial leve na borda (ML Kit), captura de voz, reprodução TTS/mídia e telemetria. |
| **2. C0rt3x Core** | **Domus Server** (`i5-4590`, `mem_limit: 384m` em `domus_internal`) | **24/7** (~25W) | WebSocket Gateway, *Spatial & Presence Engine*, *Session Manager*, *Cognitive Router* (*Fast-Path* CPU `<50ms` vs. *Slow-Path* GPU), *Slave Power Manager* (WoL S3), *Tool Registry*, *Memory Engine* (`pgvector`) e *Optical Watcher*. |
| **3. C0rt3x Compute** | **PC Gamer Slave** (RAM + GPU dedicada) | **Sob Demanda** (`S3 Sleep` ~3W → Wake 2–3s) | `Faster-Whisper` (STT + Speaker ID), `Ollama/vLLM` (`Qwen/Llama 14B + Tool Calling`), `Piper/Kokoro` (TTS neural PT-BR) e identificação visual sob demanda. |

---

## 📚 Documentação Técnica Completa

- 🏛️ **[ARCHITECTURE.md](./docs/ARCHITECTURE.md)** — Blueprint completo do **C0rt3x** e dos **7 módulos internos do C0rt3x Core**, isolamento *Dois Mundos*, orçamento de RAM e ciclo de energia S3.
- 🔌 **[WEBSOCKET_CONTRACT_V2.md](./docs/WEBSOCKET_CONTRACT_V2.md)** — Evolução do protocolo bidirecional Full-Duplex do `domus-node-sdk` (`/api/nodes/{node_id}/channel`) com eventos de presença, voz, handoff e áudio.
- 💿 **[OPTICAL_MULTIROOM_SPEC.md](./docs/OPTICAL_MULTIROOM_SPEC.md)** — Pipeline completo do leitor óptico (`/dev/sr0` + `pyudev` + `libdiscid` + MusicBrainz), janela `expect_reply_seconds` e áudio multi-ambiente com auto-ripping FLAC.

### Decisões Arquiteturais (ADRs)
- [ADR 0001 — Arquitetura Master/Slave com Suspensão S3 e Wake-on-LAN](./docs/adr/0001-master-slave-s3-wol.md)
- [ADR 0002 — Sessão Centrada no Morador & Handoff Espacial ("Follow-Me")](./docs/adr/0002-spatial-session-handoff.md)
- [ADR 0003 — Memória Estruturada (`pgvector`) + Tool Calling (MCP) em vez de Fine-Tuning](./docs/adr/0003-rag-pgvector-vs-finetuning.md)

---

## 🗺️ Roadmap de Implementação

- [ ] **Fase 1 — Fundação `C0rt3x Core`:** Stack Docker em `domus_internal` (`mem_limit: 384m`), database `cortex_db` com `pgvector` no `postgres-domus`, orquestrador WoL S3 para o PC Gamer e integração das Tools (`despensa`, `carteira`, `iot`, `notify`).
- [ ] **Fase 2 — Mídia Física & Multi-Room:** Deploy de `Navidrome` + `Music Assistant`, watcher `pyudev` em `/dev/sr0` + `libdiscid`/MusicBrainz, resposta sem wake-word (`expect_reply_seconds`) e ripping automático em FLAC.
- [ ] **Fase 3 — Evolução da Borda (`domus-node-sdk` v2):** Eventos WebSocket v2, wake-word local (`openWakeWord`/`Sherpa-ONNX`), detecção facial ML Kit na borda e handoff *Follow-Me* entre cômodos e rua (Tailnet + Apprise).
- [ ] **Fase 4 — Rotinas Autônomas Always-On:** Sensores ESP32 mmWave (`LD2410`), automação local sem nuvem e aprendizado contínuo de rotinas via memória vetorial.

---

## 🛡️ Segurança & Privacidade

- **Zero Nuvem por Padrão:** Inferência, transcrição de voz, síntese de fala e memória vetorial permanecem 100% na rede local doméstica e Tailscale VPN.
- **Isolamento "Dois Mundos":** O `C0rt3x Core` reside exclusivamente nas redes privadas do Domus (`domus_internal`, `domus_db`, `notify_bus`). Integrações com serviços externos de produto (como *Minha Despensa* e *Carteira*) ocorrem apenas via chamadas HTTPS autenticadas por token de serviço dedicado, sem pontes de rede Docker.
- **Privacidade de Câmeras:** Detecção facial roda na borda (Android ML Kit) sem gravação contínua de vídeo em disco.
