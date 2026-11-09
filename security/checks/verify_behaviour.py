"""Проверка функций исходного приложения на отдельной учебной базе.

Запускать только с RISKFR_ISOLATED=YES: таблицы accounts и transactions
в указанной базе очищаются. Рабочие системы использовать нельзя.
Исходные файлы приложения не изменяются, HTTP-сервер не запускается.
"""
import asyncio
import hashlib
import importlib
import json
import os
from pathlib import Path

import asyncpg
from fastapi import HTTPException

assert os.environ.get("RISKFR_ISOLATED") == "YES", "Требуется отдельная учебная база"
from app import crud, db
from app.security import get_current_user_id

queries = []
gate = None
arrivals = 0


class ObservedConnection(asyncpg.Connection):
    async def fetch(self, query, *args, **kwargs):
        queries.append({"sql": query.strip(), "parameters": list(args)})
        return await super().fetch(query, *args, **kwargs)

    async def fetchval(self, query, *args, **kwargs):
        global arrivals
        value = await super().fetchval(query, *args, **kwargs)
        if gate is not None and query.startswith("SELECT balance_cents"):
            arrivals += 1
            if arrivals == 2:
                gate.set()
            await asyncio.wait_for(gate.wait(), timeout=10)
        return value


async def reset():
    async with db._pool.acquire() as c:
        await c.execute("TRUNCATE transactions, accounts RESTART IDENTITY")
        await c.execute("INSERT INTO accounts(owner_user_id,balance_cents) VALUES(1,500000),(2,250000)")
    await crud.get_redis().flushdb()


async def main():
    global gate, arrivals
    result = {"scope": "Отдельная учебная база; прямые вызовы функций, не HTTP-проверка",
              "source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('app').glob('*.py'))}}
    try:
        importlib.import_module("app.main")
        result["application_import"] = "успешно"
    except ImportError as e:
        result["application_import"] = {"status": "ошибка", "reason": str(e)}
    db._pool = await asyncpg.create_pool(os.environ["POSTGRES_DSN"], min_size=1, max_size=5, connection_class=ObservedConnection)
    await db.init_db()
    await reset()
    try:
        await crud.transfer(2, 1, 2, 100)
        result["ownership_check"] = "проверка не сработала"
    except HTTPException as e:
        result["ownership_check"] = {"status_code": e.status_code, "expected": 403}
    forged_identity = await get_current_user_id("1")
    tx = await crud.transfer(forged_identity, 1, 2, 100)
    own_history = await crud.list_transactions(2, 20, None)
    victim_history = await crud.list_transactions(forged_identity, 20, None)
    result["manual_idor"] = {"claimed_identity": forged_identity, "created_transaction": tx,
                              "rows_for_user_2": len(own_history), "rows_after_claiming_user_1": len(victim_history),
                              "conclusion": "Проверка владельца есть, но её результат зависит от неподтверждённого заголовка"}
    payloads = ["' OR 1=1 --", "%'; DROP TABLE accounts; --", "1' UNION SELECT 1,2,3,4,now() --", "' AND pg_sleep(2) IS NULL --", "%", "_"]
    checks = []
    for value in payloads:
        rows = await crud.list_transactions(2, 100, value)
        checks.append({"search": value, "returned_rows": len(rows), "sql": queries[-1]})
    try:
        await get_current_user_id("1 OR 1=1")
        invalid_header = "принят"
    except HTTPException as e:
        invalid_header = e.status_code
    async with db._pool.acquire() as c:
        account_count = await c.fetchval("SELECT COUNT(*) FROM accounts")
    result["sql_injection"] = {"cases": checks, "invalid_identity_header_status": invalid_header,
                               "remaining_accounts": account_count, "conclusion": "SQL-инъекция указанными строками не подтверждена; значения передаются отдельно от текста SQL"}
    await crud.get_redis().set("tx:1:20:", "подменённое значение")
    result["redis_history_suppression"] = {"rows_before": len(victim_history), "rows_after": len(await crud.list_transactions(1,20,None))}
    await crud.transfer(1,1,2,1)
    result["redis_invalidation"] = {"history_key_remaining": bool(await crud.get_redis().exists("tx:1:20:"))}
    await reset()
    gate = asyncio.Event()
    arrivals = 0
    tx_ids = await asyncio.gather(crud.transfer(1,1,2,400000), crud.transfer(1,1,2,400000))
    gate = None
    async with db._pool.acquire() as c:
        balance = await c.fetchval("SELECT balance_cents FROM accounts WHERE id=1")
    result["concurrent_transfers"] = {"starting_balance":500000,"each_amount":400000,"transaction_ids":tx_ids,"final_balance":balance,
                                       "method": "Два чтения остатка синхронизированы перед обновлением; запросы и транзакции приложения не изменены"}
    await reset()
    original_redis = crud.get_redis
    class FailedRedis:
        async def delete(self, key):
            raise ConnectionError("Учебная имитация отказа Redis")
    crud.get_redis = lambda: FailedRedis()
    try:
        await crud.transfer(1,1,2,100)
    except ConnectionError:
        pass
    finally:
        crud.get_redis = original_redis
    retry_tx = await crud.transfer(1,1,2,100)
    async with db._pool.acquire() as c:
        count = await c.fetchval("SELECT COUNT(*) FROM transactions")
        balance = await c.fetchval("SELECT balance_cents FROM accounts WHERE id=1")
    result["retry_after_redis_failure"] = {"retry_transaction_id":retry_tx,"committed_transfers":count,"final_balance":balance}
    await crud.get_redis().aclose()
    await db._pool.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


asyncio.run(main())
