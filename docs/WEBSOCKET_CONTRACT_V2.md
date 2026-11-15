# 🔌 Contrato WebSocket v2 — Domus Node SDK ⇄ C0rt3x Core

Este documento define a extensão **v2** do canal Socket Full-Duplex (`/api/nodes/{node_id}/channel`) implementado originalmente no `DomusWebSocketChannel` do [`domus-node-sdk`](https://github.com/solobitlabs). A extensão é retrocompatível com a telemetria e comandos de tela da v1.

---

## 1. Visão Geral da Comunicação

- **Transporte:** WebSocket Full-Duplex persistente (`wss://cortex.domus.solobit.com.br/api/nodes/{node_id}/channel` ou fallback direto LAN/Tailscale).
- **Keep-Alive:** Ping/Pong a cada `15s` com reconexão exponencial automática no SDK Android.
- **Cabeçalhos Obrigatórios:**
  - `X-Node-Id`: Identificador único do dispositivo (ex: `tab-cozinha`, `kiosk-banheiro`, `tv-sala`, `mobile-will`).
  - `User-Agent`: `DomusNode-SDK/2.0`.

---

## 2. Eventos de Subida (Node Android ➔ C0rt3x Core)

Todos os eventos cognitivos enviados pelos nós seguem o envelope `"type": "CORTEX_EVENT"`.

### 2.1. `PRESENCE_DETECTED`
Disparado localmente pelo node quando a câmera frontal (via Google ML Kit Face Detection na borda) ou sensor acoplado detecta presença humana. **Não envia frames de vídeo contínuo.**

```json
{
  "type": "CORTEX_EVENT",
  "node_id": "kiosk-banheiro",
  "room": "banheiro",
  "event": "PRESENCE_DETECTED",
  "payload": {
    "source": "CAMERA_MLKIT",
    "face_detected": true,
    "person_hint": "will",
    "confidence": 0.94,
    "timestamp": "2026-11-15T13:20:05Z"
  }
}
```

### 2.2. `WAKE_WORD_DETECTED`
Disparado quando o motor local de palavra de ativação (`openWakeWord` ou `Sherpa-ONNX`) no aparelho escuta `"Cortex"`. Sinaliza ao Core para preparar a sessão e aguardar o áudio.

```json
{
  "type": "CORTEX_EVENT",
  "node_id": "tab-cozinha",
  "room": "cozinha",
  "event": "WAKE_WORD_DETECTED",
  "payload": {
    "engine": "openWakeWord",
    "keyword": "cortex",
    "score": 0.91,
    "timestamp": "2026-11-15T13:20:06Z"
  }
}
```

### 2.3. `VOICE_COMMAND_AUDIO`
Carrega o áudio capturado após a wake-word **ou** durante uma janela de resposta contínua (`expect_reply_seconds`).

```json
{
  "type": "CORTEX_EVENT",
  "node_id": "tab-cozinha",
  "room": "cozinha",
  "event": "VOICE_COMMAND_AUDIO",
  "payload": {
    "session_id": "sess-will-01",
    "in_reply_to": null,
    "wake_word_bypassed": false,
    "codec": "opus_16khz",
    "snr_db": 24.5,
    "audio_b64": "<chunks_base64_ou_stream_binario>"
  }
}
```

### 2.4. `LOCATION_STATE_CHANGED`
Enviado pelo `domus-mobile` no telefone pessoal do morador ao entrar ou sair do Wi-Fi residencial (`DOMUS-LAN-5G`), permitindo que o `Spatial Engine` alterne entre entrega local e entrega externa via Tailnet/Apprise.

```json
{
  "type": "CORTEX_EVENT",
  "node_id": "mobile-will",
  "room": "rua_tailnet",
  "event": "LOCATION_STATE_CHANGED",
  "payload": {
    "user": "will",
    "wifi_ssid": null,
    "tailscale_ip": "100.x.y.44",
    "home_present": false
  }
}
```

---

## 3. Ações de Descida (C0rt3x Core ➔ Node Android)

Seguem o contrato de `RemoteCommand` (`command_id`, `action`, `payload`) já tratado pelo `BaseDomusDaemonService` no SDK Android.

### 3.1. `CORTEX_SPEAK`
Ordena que o node reproduza a fala sintetizada (TTS) e opcionalmente exiba legenda/cartão no HUD. Se `expect_reply_seconds > 0`, o node **abre o microfone automaticamente** ao término do áudio sem exigir nova wake-word.

```json
{
  "command_id": "cmd-cortex-901",
  "action": "CORTEX_SPEAK",
  "payload": {
    "session_id": "sess-will-20261115",
    "text": "Will, um CD de Arctic Monkeys foi inserido. Deseja reproduzir a mídia?",
    "audio_url": "https://cortex.domus.solobit.com.br/api/tts/stream/cmd-cortex-901.wav",
    "show_hud": true,
    "expect_reply_seconds": 8
  }
}
```

### 3.2. `CORTEX_LISTEN_NOW`
Força a abertura imediata do microfone com indicador visual de escuta ativa no HUD.

```json
{
  "command_id": "cmd-cortex-902",
  "action": "CORTEX_LISTEN_NOW",
  "payload": {
    "session_id": "sess-will-20261115",
    "timeout_seconds": 8,
    "show_listening_ring": true
  }
}
```

### 3.3. `CORTEX_HANDOFF_IN`
Notifica o node de destino (ex: `kiosk-banheiro`) que uma conversa iniciada em outro cômodo (`cozinha`) acaba de ser transferida para ele, acordando a tela suavemente e exibindo o card de contexto.

```json
{
  "command_id": "cmd-cortex-903",
  "action": "CORTEX_HANDOFF_IN",
  "payload": {
    "session_id": "sess-will-20261115",
    "origin_room": "cozinha",
    "wake_screen_softly": true,
    "summary_card": {
      "title": "Receita sugerida",
      "items": [
        "Creme de leite (vence em 2d)",
        "Arroz arbóreo"
      ]
    }
  }
}
```

### 3.4. `MEDIA_PLAY_STREAM`
Instrui o node (ou sua caixa Bluetooth/Alexa pareada) a conectar-se a um stream de mídia multi-ambiente sincronizado.

```json
{
  "command_id": "cmd-cortex-904",
  "action": "MEDIA_PLAY_STREAM",
  "payload": {
    "zone": "quarto",
    "route_via": "bluetooth_alexa_or_speaker",
    "stream_url": "https://music.domus.solobit.com.br/stream/snapcast/quarto",
    "track_meta": {
      "artist": "Arctic Monkeys",
      "album": "AM",
      "title": "Fireside",
      "track": 9
    }
  }
}
```
