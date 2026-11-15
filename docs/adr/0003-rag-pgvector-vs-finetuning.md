# ADR 0003: Memória Estruturada (`pgvector`) + Tool Calling (MCP) em vez de Fine-Tuning

- **Status:** Aceito (15/11/2026)
- **Contexto:** O C0rt3x precisa compreender a rotina da casa, hábitos dos moradores, estoque dinâmico da despensa, lançamentos financeiros da carteira e estado dos sensores IoT. Treinar pesos de um LLM localmente (fine-tuning contínuo) toda vez que dados da casa mudam seria lento, custoso e propenso a alucinações com informações obsoletas.
- **Decisão:** Manter o modelo base do PC Gamer congelado (ex: `Qwen`/`Llama` com suporte a Tool Calling) e fornecer contexto dinâmico por meio de duas camadas no **C0rt3x Core**:
  1. **Memória em 3 Camadas no `postgres-domus` (`cortex_db` + `pgvector`):** *Working Memory* em RAM, *Episodic Events* em SQL temporal e *Semantic Memories* recuperadas via busca vetorial (RAG).
  2. **Tool / MCP Registry:** Funções tipadas que consultam APIs em tempo real (`Minha Despensa`, `Carteira`, `AirPower/HA`, `Music Assistant`, `Apprise`).
- **Consequências:** Atualização instantânea do conhecimento da casa sem retreinar modelos, facilidade de trocar o modelo LLM no futuro sem perder a memória acumulada da residência e isolamento completo entre dados privados da casa e produtos externos.
