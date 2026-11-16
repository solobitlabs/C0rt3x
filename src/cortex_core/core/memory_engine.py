"""Motor de memoria em 3 camadas (Working, Episodic SQL, Semantic/Vector)."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import math
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger("cortex.memory")


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Calcula similaridade cosseno segura entre dois vetores."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass
class EpisodicRecord:
    user_id: str
    event_type: str
    room: str
    summary: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SemanticMemoryRecord:
    user_id: str
    fact: str
    embedding: Optional[List[float]] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryEngine:
    """Gerencia memoria episodica e semantica em postgres-domus (ou cache em memoria)."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        self._database_url = database_url
        self._pool: Optional[asyncpg.Pool] = None
        self._episodic_fallback: List[EpisodicRecord] = []
        self._semantic_fallback: List[SemanticMemoryRecord] = []

    @property
    def using_postgres(self) -> bool:
        return self._pool is not None

    async def initialize(self) -> None:
        """Abre pool asyncpg e garante tabelas basicas no postgres-domus."""
        if not self._database_url:
            logger.info("MemoryEngine iniciado em modo memoria (sem database_url).")
            return
        try:
            self._pool = await asyncpg.create_pool(dsn=self._database_url, min_size=1, max_size=4)
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS episodic_events (
                        id BIGSERIAL PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        room TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE INDEX IF NOT EXISTS idx_episodic_user_time
                        ON episodic_events (user_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS semantic_memories (
                        id BIGSERIAL PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        fact TEXT NOT NULL,
                        embedding DOUBLE PRECISION[],
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE INDEX IF NOT EXISTS idx_semantic_user
                        ON semantic_memories (user_id);
                    """
                )
            logger.info("MemoryEngine conectado ao postgres-domus com sucesso.")
        except Exception as exc:
            logger.warning("Falha ao conectar no postgres-domus (%s). Usando fallback em RAM.", exc)
            self._pool = None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def record_episodic_event(
        self,
        user_id: str,
        event_type: str,
        room: str,
        summary: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        clean_user = user_id.strip().lower()
        meta = metadata or {}
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO episodic_events (user_id, event_type, room, summary, metadata)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    """,
                    clean_user,
                    event_type.strip(),
                    room.strip().lower(),
                    summary.strip(),
                    json.dumps(meta),
                )
            return

        self._episodic_fallback.append(
            EpisodicRecord(
                user_id=clean_user,
                event_type=event_type.strip(),
                room=room.strip().lower(),
                summary=summary.strip(),
                metadata=meta,
            )
        )

    async def save_semantic_memory(
        self,
        user_id: str,
        fact: str,
        embedding: Optional[List[float]] = None,
    ) -> None:
        clean_user = user_id.strip().lower()
        clean_fact = fact.strip()
        if not clean_fact:
            return
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO semantic_memories (user_id, fact, embedding)
                    VALUES ($1, $2, $3)
                    """,
                    clean_user,
                    clean_fact,
                    embedding,
                )
            return

        self._semantic_fallback.append(
            SemanticMemoryRecord(user_id=clean_user, fact=clean_fact, embedding=embedding)
        )

    async def search_semantic_memories(
        self,
        user_id: str,
        query_embedding: Optional[List[float]] = None,
        query_text: str = "",
        limit: int = 5,
    ) -> List[str]:
        clean_user = user_id.strip().lower()
        rows: List[tuple[str, Optional[List[float]]]] = []

        if self._pool is not None:
            async with self._pool.acquire() as conn:
                db_rows = await conn.fetch(
                    "SELECT fact, embedding FROM semantic_memories WHERE user_id = $1 ORDER BY created_at DESC LIMIT 200",
                    clean_user,
                )
                rows = [(r["fact"], r["embedding"]) for r in db_rows]
        else:
            rows = [(m.fact, m.embedding) for m in self._semantic_fallback if m.user_id == clean_user]

        if not rows:
            return []

        if query_embedding:
            scored = sorted(
                rows,
                key=lambda item: cosine_similarity(query_embedding, item[1] or []),
                reverse=True,
            )
            return [fact for fact, _ in scored[:limit]]

        # Fallback lexical simples quando nao ha vetor de embedding
        tokens = {tok for tok in query_text.lower().split() if len(tok) > 2}
        if not tokens:
            return [fact for fact, _ in rows[:limit]]

        scored_lexical = sorted(
            rows,
            key=lambda item: sum(1 for tok in tokens if tok in item[0].lower()),
            reverse=True,
        )
        return [fact for fact, _ in scored_lexical[:limit]]

    async def list_semantic_memories(self, user_id: str, limit: int = 20) -> List[str]:
        clean_user = user_id.strip().lower()
        if self._pool is not None:
            async with self._pool.acquire() as conn:
                db_rows = await conn.fetch(
                    "SELECT fact FROM semantic_memories WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
                    clean_user,
                    limit,
                )
                return [r["fact"] for r in db_rows]
        return [m.fact for m in reversed(self._semantic_fallback) if m.user_id == clean_user][:limit]
