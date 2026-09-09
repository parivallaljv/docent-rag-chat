"""asyncpg connection pool setup, with the pgvector type codec registered on
every new connection so plain Python lists/numpy arrays can be passed and
received as `vector` columns directly in raw SQL, no manual (de)serialization.
"""
from __future__ import annotations

from typing import Optional

import asyncpg
from pgvector.asyncpg import register_vector

from ..core.config import settings

_pool: Optional[asyncpg.Pool] = None


async def create_pool() -> asyncpg.Pool:
    """Create (once) and return the shared connection pool. Safe to call
    multiple times; subsequent calls return the existing pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.SUPABASE_DB_URL,
            min_size=1,
            max_size=10,
            # Runs on every new physical connection the pool opens, so every
            # connection -- not just the first -- can bind/parse `vector` columns.
            init=register_vector,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """Return the already-created pool. Raises if called before create_pool()
    (i.e. before the app's startup/lifespan has run)."""
    if _pool is None:
        raise RuntimeError("DB pool not initialized. Call create_pool() during app startup.")
    return _pool
