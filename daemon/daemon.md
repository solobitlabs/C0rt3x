# Domus Cortex Edge Daemon (`daemon`)

## 1. O que é
O **`domus-cortex-daemon`** (`daemon/daemon.py`) é o agente de telemetria leve que roda no host **C0rt3x Compute** (`cortex-compute`), tratando a máquina de GPU como um **Edge Compute Node** monitorado continuamente pelo **Domus Dashboard**.

---

## 2. Como Funciona
- Roda no container `domus_cortex_daemon` (`mem_limit: 128m`, `pid: host`, `network_mode: host`, `restart: unless-stopped`).
- Lê métricas somente-leitura diretamente do host:
  - `/proc` → `/host/proc`: CPU %, contagem de cores, load average, temperatura CPU (`k10temp`), RAM/Swap e lista de processos (Top CPU e RAM).
  - `/sys` → `/host/sys`: telemetria nativa da GPU AMD Radeon RX 7600 em `/sys/class/drm/card1/device` (`gpu_busy_percent`, `mem_info_vram_used`, `mem_info_vram_total`, `hwmon/*/temp1_input`, `hwmon/*/power1_average`).
  - `/var/run/docker.sock`: estado dos containers locais (`cortex_ollama`, `cortex_worker`, `domus_cortex_daemon`).
  - `http://127.0.0.1:11434/api/ps` e `/api/tags`: modelos Ollama carregados em VRAM e disponíveis em disco.
- A cada `DAEMON_INTERVAL_SECONDS` (padrão `10s`), envia o snapshot via `POST https://stats.domus.solobit.com.br/api/compute/telemetry` com `Authorization: Bearer <COMPUTE_TELEMETRY_TOKEN>`.

---

## 3. Detecção Online / Offline
- O padrão **Push** evita que o `domus_dashboard` fique bloqueado em timeouts TCP quando o `cortex-compute` estiver desligado.
- O Dashboard marca o nó como `ONLINE` enquanto o último snapshot tiver `<= 45s` de idade; após isso, exibe `OFFLINE` com o tempo decorrido desde o último sinal.
