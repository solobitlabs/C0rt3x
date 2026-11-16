# Domus C0rt3x (`domus-cortex`)

## 1. Visão Geral
O **Domus C0rt3x** é o núcleo de inteligência residencial local da **SoloBit Labs / Domus Server**. Ele opera 100% em infraestrutura própria (on-premise + Tailnet privada), sem envio de voz, presença, métricas domésticas ou memórias para provedores externos de nuvem.

---

## 2. Atores do Ecossistema
- **Morador (`user_id`):** interage por texto ou voz via Domus Dashboard, Domus Mobile (Android) ou Domus TV (Android TV).
- **C0rt3x Core (`cortex_core`):** orquestrador central 24/7 no Domus Server (`https://cortex.domus.solobit.com.br`). Gerencia sessões, roteamento Fast/Slow-Path, ferramentas e memória em PostgreSQL (`cortex_db`).
- **C0rt3x Compute (`cortex_worker` + `cortex_ollama`):** nó de inferência pesada com GPU AMD Radeon RX 7600 (ROCm) no host `cortex-compute` (`100.122.5.99:8090` via Tailnet). Executa LLM (`qwen2.5:7b`), embeddings (`nomic-embed-text`), STT (`faster-whisper`) e TTS (`piper-tts`).
- **Domus Cortex Edge Daemon (`domus_cortex_daemon`):** agente leve no `cortex-compute` que coleta CPU, RAM, Disco, processos, containers e telemetria sysfs da RX 7600 e envia snapshots a cada 10s para o Domus Dashboard.
- **Domus Dashboard (`domus_dashboard`):** painel central (`https://stats.domus.solobit.com.br`) com proxy autenticado para chat/voz do C0rt3x e visualização lado a lado do Domus Server e do `cortex-compute`.

---

## 3. Arquitetura e Fluxo de Dados

```text
[Domus Dashboard / Mobile / TV]
       │ HTTPS (lan-tailnet-only)
       ▼
[cortex_core :8000 (Domus Server)] ────► [postgres-domus (cortex_db)]
       │                                 [domus_dashboard :8000/api/stats]
       │                                 [apprise :8000 (notify_bus)]
       │ Tailnet + Bearer Token (100.122.5.99:8090)
       ▼
[cortex_worker :8090 (cortex-compute)]
       ├──► [cortex_ollama :11434] (ROCm RX 7600: qwen2.5:7b + nomic-embed-text)
       ├──► Faster-Whisper (STT PT-BR)
       └──► Piper TTS (pt_BR-faber-medium WAV)
```

---

## 4. Funcionamento e Regras Principais
1. **Roteamento Cognitivo em 2 Velocidades:**
   - **Fast-Path (`< 50ms` na CPU):** comandos determinísticos como telemetria do Domus (`domus.stats.server`), GPU/Ollama (`domus.stats.compute`), AdGuard (`domus.stats.dns`), notificações Apprise (`notify.send_external`) e gravação de memória (`memory.save`).
   - **Slow-Path (GPU Slave):** perguntas abertas e raciocínio contextual delegados ao `qwen2.5:7b` com injeção das últimas interações e memórias semânticas.
   - **Modo Degradado Gracioso:** se o `cortex-compute` estiver desligado, o Fast-Path e a busca lexical de memórias continuam operando normalmente no Domus Server.
2. **Memória em 3 Camadas:**
   - *Working Memory:* janela recente por usuário em RAM (`SessionManager`).
   - *Episodic SQL:* eventos gravados em `episodic_events` (`postgres-domus`).
   - *Semantic Memory:* fatos e preferências com vetores `nomic-embed-text` em `semantic_memories` e busca por similaridade cosseno (com fallback lexical).
3. **Diretrizes de Segurança:**
   - Zero port-forwarding; acesso restrito a LAN (`192.168.15.0/24`) e Tailnet (`100.64.0.0/10`).
   - Segredos apenas em `.env` (`chmod 600`), nunca versionados no Git.
   - Comunicação Core ↔ Worker autenticada por `Authorization: Bearer`.
