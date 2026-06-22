import asyncpg
import os

_pool: asyncpg.Pool | None = None

async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=os.environ["POSTGRES_DSN"], min_size=1, max_size=5)
    return _pool

async def init_db() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS accounts(
            id BIGSERIAL PRIMARY KEY,
            owner_user_id BIGINT NOT NULL,
            balance_cents BIGINT NOT NULL DEFAULT 0
        );
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions(
            id BIGSERIAL PRIMARY KEY,
            from_account_id BIGINT NOT NULL,
            to_account_id BIGINT NOT NULL,
            amount_cents BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """)
        count = await conn.fetchval("SELECT COUNT(*) FROM accounts;")
        if count == 0:
            await conn.execute("""
            INSERT INTO accounts(owner_user_id, balance_cents)
            VALUES (1, 500000), (2, 250000);
            """)
