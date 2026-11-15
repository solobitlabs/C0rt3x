# ADR 0001: Arquitetura Master/Slave com Suspensão S3 e Wake-on-LAN

- **Status:** Aceito (15/11/2026)
- **Contexto:** O Domus Server opera 24/7 em hardware econômico (`Intel Core i5-4590`, `7.2 GiB RAM`), suficiente para serviços domésticos, rede e automação, porém incapaz de executar LLMs modernos, STT e visão computacional pesada em tempo real. Por outro lado, o morador possui um PC Gamer com GPU dedicada e maior capacidade de RAM, cujo consumo contínuo 24/7 seria energeticamente caro.
- **Decisão:** Adotar uma topologia **Master/Slave Híbrida**:
  1. O **C0rt3x Core** roda 24/7 no Domus Server (`mem_limit: 384m`), tratando comandos determinísticos (*Fast-Path* `<50ms`), mantendo sessões, presença e watchers físicos.
  2. O **PC Gamer Slave** atua como worker de computação (*Slow-Path*), mantido em **Suspensão na RAM (S3 Sleep, ~2–5W)** quando ocioso, acordado via **Wake-on-LAN (Magic Packet UDP:9)** em **2–3 segundos** sob demanda e suspenso automaticamente após **10 minutos** sem requisições (`IDLE_TIMEOUT=600s`).
- **Consequências:** Economia expressiva de energia mantendo latência conversacional aceitável (~2.5s no primeiro comando complexo com feedback sonoro imediato no node), superando a lentidão do boot frio S5 (25–45s) e o custo elétrico de deixar a GPU ligada 24/7.
