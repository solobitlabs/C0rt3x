# ADR 0002: Sessão Centrada no Morador & Handoff Espacial ("Follow-Me")

- **Status:** Aceito (15/11/2026)
- **Contexto:** Em assistentes convencionais (ex: Alexa), o estado da interação fica vinculado ao dispositivo que captou o áudio. Se o morador fala na cozinha e caminha até o banheiro enquanto a resposta é processada, ou se sai de casa, a resposta se perde no cômodo vazio.
- **Decisão:**
  1. Centralizar todas as sessões de diálogo no **C0rt3x Core** indexadas pelo identificador do morador (`session:{user_id}`), tratando tablets, celulares quiosque e TVs como terminais stateless de entrada/saída via WebSocket (`domus-node-sdk`).
  2. Implementar o **Spatial & Presence Engine** calculando o melhor destino de entrega (`active_output_node`) por fusão ponderada com decaimento temporal (TTL): Voz SNR (`100`), Detecção Facial ML Kit na borda (`80`, TTL `30s`), Radar mmWave ESP32 (`50`, TTL `60s`) e transição de rede Wi-Fi → Tailnet (`rua_tailnet`, roteando via `domus-mobile` / Apprise Telegram).
- **Consequências:** Continuidade natural da conversa entre cômodos e para fora da residência, mantendo o processamento de vídeo estritamente na borda (sem streaming de vídeo 24/7 pela LAN).
