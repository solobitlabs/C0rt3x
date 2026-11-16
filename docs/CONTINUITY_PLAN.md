# Plano de Continuidade — Ecossistema Domus & C0rt3x

Este plano define a sequência de implementação da infraestrutura base da casa antes da ativação do *Follow-Me* multi-cômodo, garantindo que os **Edge Nodes** forneçam dados confiáveis e que os **dispositivos IoT** sejam descobertos, validados e mantidos de forma determinística.

---

## Fase 1 — Fortalecimento dos Edge Nodes (`domus-node-sdk` + `domus_dashboard`)
**Objetivo:** Transformar cada nó Android (`domus-tv`, `domus-mobile`) e de computação (`cortex-compute`) em um sensor e atuador confiável com telemetria precisa e capabilities validadas.

1. **Modelo Unificado de Telemetria & Capabilities (`domus-node-sdk` & `domus_dashboard`):**
   - Persistir `permissions` completos no `domus_dashboard` (`overlay`, `battery_unrestricted`, `accessibility`, `write_secure_settings`).
   - Adicionar ao `NodeTelemetryPayload`:
     - `room`: cômodo atribuído ao nó (ex.: `sala`, `quarto`, `cozinha`, `movel`).
     - `battery`: nível `%`, `is_charging`, `temperature_c`, `power_source` (`ac`, `usb`, `battery`).
     - `peripherals`: microfone disponível, saída de áudio ativa (`speaker`, `bluetooth`, `hdmi`), dispositivos USB/HID conectados, dispositivos BLE próximos com `rssi`.
     - `capabilities_health`: resultado do autoteste de cada capability declarada (`audio.tts`, `audio.mic`, `display.kiosk`, `ble.scan`, `lan.scan`, `hdmi.cec`).
2. **Autodiagnóstico nos Apps (`domus-tv` / `domus-mobile`):**
   - Tela de diagnóstico no app e no Dashboard exibindo quais capabilities estão `OK`, `DEGRADED` ou `MISSING_PERMISSION`, com ação direta de correção.

---

## Fase 2 — Barramento IoT & Descoberta de Dispositivos (Domus Server)
**Objetivo:** Criar a camada de descoberta, cadastro e manutenção de dispositivos reais da casa (lâmpadas, ar-condicionado, geladeira, tomadas, TVs).

1. **Broker MQTT Central (`eclipse-mosquitto`):**
   - Subir container leve (`mem_limit: 64m`) na rede `domus_internal` com autenticação por usuário/senha e persistência de estado retido.
2. **Motor de Descoberta na LAN & BLE (`domus-iot-discovery`):**
   - **Descoberta ativa no servidor:** varredura periódica mDNS/Zeroconf (`_hap._tcp`, `_googlecast._tcp`, `_esphomelib._tcp`, `_airplay._tcp`, `_tuya._tcp`) e SSDP/UPnP na LAN `192.168.15.0/24`.
   - **Descoberta delegada aos Edge Nodes:** os nós Android enviam lista de beacons BLE / dispositivos Bluetooth próximos com RSSI.
   - Fila de **Dispositivos Descobertos (Pendentes de Adoção)** no Domus Dashboard para o morador nomear, escolher o cômodo e aprovar.
3. **Inventário & Manutenção IoT (`postgres-domus` + Dashboard):**
   - Tabelas `iot_devices` (`device_id`, `name`, `category` [`light`, `ac`, `fridge`, `plug`, `tv`, `sensor`], `room`, `protocol` [`mqtt`, `tuya_local`, `lg_thinq`, `http`, `ir`], `ip_address`, `mac_address`, `capabilities`, `last_seen`, `state_json`) e `iot_maintenance_logs`.
   - Aba **IoT & Dispositivos** no Domus Dashboard mostrando estado em tempo real, sinal/latência, alertas de queda (via Apprise) e controle manual (ligar/desligar, temperatura do AC, status da geladeira).

---

## Fase 3 — Integração Real do C0rt3x Core (`home.iot.*` & `edge.nodes.*`)
**Objetivo:** Conectar o `ToolRegistry` do `cortex_core` aos dispositivos e Edge Nodes reais.

1. **Tools Reais de Casa:**
   - `home.iot.light(room, state, brightness)` → publica no tópico MQTT / driver do dispositivo real.
   - `home.iot.ac(room, power, target_temp, mode)` → controla ar-condicionado e consulta temperatura ambiente.
   - `home.iot.appliance.status(category)` → consulta estado/alertas de eletrodomésticos (ex.: geladeira, energia).
   - `edge.nodes.status()` → consulta saúde, áudio, bateria e periféricos de todos os Edge Nodes.
2. **Validação Determinística:**
   - Testes automatizados de contrato entre `cortex_core`, `eclipse-mosquitto` e `iot_devices` antes de habilitar comandos por voz em produção.

---

## Fase 4 — *Follow-Me* & Multiroom Óptico
**Objetivo:** Com a base de nós, periféricos e IoT validada, ativar a entrega contextual contínua.

1. Conectar `domus-tv` e `domus-mobile` ao `wss://cortex.domus.solobit.com.br/api/nodes/{node_id}/channel`.
2. Calibrar pesos do `SpatialEngine` com sinais reais (`PRESENCE_DETECTED`, BLE RSSI, `VOICE_SNR`, estado da tela).
3. Ativar resposta falada automática no nó onde o morador se encontra (*handoff* silencioso entre cômodos).
