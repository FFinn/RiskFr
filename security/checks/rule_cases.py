"""Искусственные примеры только для проверки правил; не часть приложения."""
from fastapi import Header

async def list_transactions(user_id, limit, search):
    conn = None
    # ruleid: sql-input-in-query
    await conn.fetch("SELECT * FROM transactions WHERE id = '" + search + "'")
    # ok: sql-input-in-query
    await conn.fetch("SELECT * FROM transactions WHERE id=$1", search)
    sql = "SELECT * FROM transactions WHERE owner_user_id=$1"
    i = 2
    # ruleid: sql-dynamic-text-review
    sql += f" LIMIT ${i}"
    # ok: sql-input-in-query
    await conn.fetch(sql, user_id, limit)

async def identity(x_user_id: str | None = Header(default=None)) -> int:
    # ruleid: untrusted-user-identity
    return int(x_user_id)
