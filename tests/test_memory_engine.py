"""Testes unitarios para MemoryEngine (fallback RAM e busca semantica)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cortex_core.core.memory_engine import MemoryEngine, cosine_similarity  # noqa: E402


def test_cosine_similarity() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([], [1.0]) == 0.0


@pytest.mark.asyncio
async def test_memory_engine_in_memory_fallback_and_search() -> None:
    mem = MemoryEngine(database_url=None)
    await mem.initialize()
    assert mem.using_postgres is False

    await mem.record_episodic_event("will", "CD_INSERTED", "sala", "Arctic Monkeys - AM")
    await mem.save_semantic_memory("will", "Will prefere respostas curtas no banheiro", [0.9, 0.1])
    await mem.save_semantic_memory("will", "Will gosta de risoto de cogumelos", [0.1, 0.9])

    top_vec = await mem.search_semantic_memories("will", query_embedding=[0.95, 0.05], limit=1)
    assert top_vec == ["Will prefere respostas curtas no banheiro"]

    top_lex = await mem.search_semantic_memories("will", query_text="risoto cogumelos", limit=1)
    assert top_lex == ["Will gosta de risoto de cogumelos"]
    await mem.close()
