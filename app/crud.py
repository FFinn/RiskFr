from fastapi import HTTPException
from app.db import get_pool
from app.redis_client import get_redis

async def _must_own_account(user_id: int, account_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        ok = await conn.fetchval(
            "SELECT 1 FROM accounts WHERE id=$1 AND owner_user_id=$2",
            account_id, user_id
        )
        if not ok:
            raise HTTPException(status_code=403, detail="Forbidden")

async def transfer(user_id: int, from_id: int, to_id: int, amount: int) -> int:
    await _must_own_account(user_id, from_id)
    pool = await get_pool()
    r = get_redis()

    async with pool.acquire() as conn:
        async with conn.transaction():
            bal = await conn.fetchval("SELECT balance_cents FROM accounts WHERE id=$1", from_id)
            if bal is None:
                raise HTTPException(status_code=404, detail="From account not found")
            if bal < amount:
                raise HTTPException(status_code=400, detail="Insufficient funds")

            to_exists = await conn.fetchval("SELECT 1 FROM accounts WHERE id=$1", to_id)
            if not to_exists:
                raise HTTPException(status_code=404, detail="To account not found")

            await conn.execute("UPDATE accounts SET balance_cents = balance_cents - $1 WHERE id=$2", amount, from_id)
            await conn.execute("UPDATE accounts SET balance_cents = balance_cents + $1 WHERE id=$2", amount, to_id)

            tx_id = await conn.fetchval(
                "INSERT INTO transactions(from_account_id,to_account_id,amount_cents) VALUES ($1,$2,$3) RETURNING id",
                from_id, to_id, amount
            )

    await r.delete(f"tx:{user_id}")
    return int(tx_id)

async def list_transactions(user_id: int, limit: int, search: str | None):
    r = get_redis()
    cache_key = f"tx:{user_id}:{limit}:{search or ''}"
    cached = await r.get(cache_key)
    if cached:
        return []

    pool = await get_pool()
    async with pool.acquire() as conn:
        sql = """
        SELECT t.id, t.from_account_id, t.to_account_id, t.amount_cents, t.created_at
        FROM transactions t
        JOIN accounts a ON a.id = t.from_account_id
        WHERE a.owner_user_id = $1
        """
        params = [user_id]
        i = 2
        if search:
            sql += f" AND CAST(t.id AS TEXT) ILIKE ${i}"
            params.append(f"%{search}%")
            i += 1
        sql += f" ORDER BY t.created_at DESC LIMIT ${i}"
        params.append(limit)
        return await conn.fetch(sql, *params)
