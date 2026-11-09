"""Проверка HTTP на одноразовых PostgreSQL и Redis.

База и Redis очищаются при подготовке. Запускать только в учебном окружении
с RISKFR_ISOLATED=YES. Запросы к приложению выполняются через HTTP.
"""
import asyncio
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import asyncpg
import redis.asyncio as redis


if os.environ.get("RISKFR_ISOLATED") != "YES":
    raise RuntimeError("Требуется отдельная учебная база")

BASE_URL = os.environ["HTTP_BASE_URL"].rstrip("/")
results = []


def request(case, method, path, expected_status, user_id=None, query=None, body=None):
    if query:
        path += "?" + urllib.parse.urlencode(query)
    headers = {}
    if user_id is not None:
        headers["X-User-Id"] = str(user_id)
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    started = time.monotonic()
    try:
        response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        status = response.status
        value = json.loads(response.read().decode("utf-8"))
    elapsed = round(time.monotonic() - started, 4)
    assert status == expected_status, (case, status, expected_status, value)
    results.append({
        "case": case,
        "method": method,
        "path": path,
        "identity_header": str(user_id) if user_id is not None else None,
        "request_body": body,
        "status": status,
        "expected_status": expected_status,
        "response": value,
        "elapsed_seconds": elapsed,
    })
    return value


async def snapshot(conn):
    accounts = await conn.fetch("SELECT id, owner_user_id, balance_cents FROM accounts ORDER BY id")
    transfers = await conn.fetch(
        "SELECT id, from_account_id, to_account_id, amount_cents FROM transactions ORDER BY id"
    )
    return {"accounts": [dict(row) for row in accounts],
            "transactions": [dict(row) for row in transfers]}


def transaction_ids(rows):
    assert isinstance(rows, list), rows
    return sorted(row["id"] for row in rows)


async def main():
    # Оба подключения относятся к одноразовому окружению запуска.
    conn = await asyncpg.connect(os.environ["POSTGRES_DSN"])
    cache = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    try:
        schema = request("Приложение отвечает", "GET", "/openapi.json", 200)
        assert "/transfer" in schema["paths"] and "/transactions" in schema["paths"]
        # Полная схема не нужна в журнале; сохраняется проверенное наличие маршрутов.
        results[-1]["response"] = {"paths": sorted(schema["paths"])}
        await conn.execute("TRUNCATE transactions, accounts RESTART IDENTITY")
        await conn.execute(
            "INSERT INTO accounts(owner_user_id,balance_cents) VALUES(1,500000),(2,250000)"
        )
        await cache.flushdb()

        tx1 = request("Контроль: перевод владельца 1", "POST", "/transfer", 200, 1,
                      body={"from_account_id": 1, "to_account_id": 2, "amount_cents": 100})
        tx2 = request("Контроль: перевод владельца 2", "POST", "/transfer", 200, 2,
                      body={"from_account_id": 2, "to_account_id": 1, "amount_cents": 50})
        own_ids = {1: [tx1["transaction_id"]], 2: [tx2["transaction_id"]]}
        assert own_ids[1] != own_ids[2]
        for uid in (1, 2):
            rows = request(f"Контроль: история владельца {uid}", "GET", "/transactions", 200, uid)
            assert transaction_ids(rows) == own_ids[uid]
            assert all(row["from_account_id"] == uid for row in rows)
            rows = request(f"Контроль: поиск своей операции владельцем {uid}", "GET", "/transactions", 200,
                           uid, query={"search": str(own_ids[uid][0])})
            assert transaction_ids(rows) == own_ids[uid]
            rows = request(f"Контроль: поиск чужой операции владельцем {uid}", "GET", "/transactions", 200,
                           uid, query={"search": str(own_ids[3 - uid][0])})
            assert transaction_ids(rows) == []

        before_probes = await snapshot(conn)
        assert len(before_probes["transactions"]) == 2
        payloads = [
            "'", "' OR 1=1 --", "%') OR 1=1 --",
            "1' UNION SELECT 1,2,3,4,now() --",
            "%'; DROP TABLE accounts; --",
            "'; SELECT pg_sleep(2); --",
            "' AND pg_sleep(2) IS NULL --",
        ]
        for uid in (1, 2):
            for payload in payloads:
                rows = request(f"SQL: поисковая строка, владелец {uid}", "GET", "/transactions", 200,
                               uid, query={"search": payload, "limit": 100})
                assert transaction_ids(rows) == [], (uid, payload, rows)
            for pattern in ("%", "_"):
                rows = request(f"Контроль шаблона поиска, владелец {uid}", "GET", "/transactions", 200,
                               uid, query={"search": pattern})
                assert transaction_ids(rows) == own_ids[uid], (uid, pattern, rows)

        request("Заголовок личности отсутствует", "GET", "/transactions", 401)
        for identity in ("1 OR 1=1", "1; DROP TABLE accounts; --", "1' UNION SELECT 1 --"):
            request("SQL: заголовок личности", "GET", "/transactions", 400, identity)
        for limit in ("1 OR 1=1", "1; DROP TABLE accounts; --", "0", "101"):
            request("SQL и границы: предел выдачи", "GET", "/transactions", 422, 1,
                    query={"limit": limit})
        request("Граница длины поиска", "GET", "/transactions", 422, 1, query={"search": "x" * 101})

        for field in ("from_account_id", "to_account_id", "amount_cents"):
            for payload in ("1 OR 1=1", "1; DROP TABLE accounts; --"):
                body = {"from_account_id": 1, "to_account_id": 2, "amount_cents": 100}
                body[field] = payload
                request(f"SQL: поле {field}", "POST", "/transfer", 422, 1, body=body)

        after_probes = await snapshot(conn)
        assert after_probes == before_probes, (before_probes, after_probes)
        # Запрос после отрицательных проб подтверждает работоспособность пути чтения.
        for uid in (1, 2):
            rows = request(f"Контроль после SQL-проб, владелец {uid}", "GET", "/transactions", 200,
                           uid, query={"search": str(own_ids[uid][0])})
            assert transaction_ids(rows) == own_ids[uid]

        request("Проверка владельца запрещает чужое списание", "POST", "/transfer", 403, 2,
                body={"from_account_id": 1, "to_account_id": 2, "amount_cents": 100})
        assert await snapshot(conn) == after_probes
        forged_rows = request("Подмена личности: чтение истории владельца 1", "GET", "/transactions", 200, 1)
        assert transaction_ids(forged_rows) == own_ids[1]
        forged_transfer = request("Подмена личности: списание со счёта владельца 1", "POST", "/transfer", 200, 1,
                                 body={"from_account_id": 1, "to_account_id": 2, "amount_cents": 100})
        after_forgery = await snapshot(conn)
        assert len(after_forgery["transactions"]) == 3
        assert after_forgery["accounts"][0]["balance_cents"] == 499850
        assert after_forgery["accounts"][1]["balance_cents"] == 250150

        report = {
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "HTTP-запросы к работающему приложению на одноразовых PostgreSQL и Redis",
            "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in sorted(Path("app").glob("*.py")) if not path.name.startswith("._")},
            "versions": {name: version(name) for name in ("fastapi", "asyncpg", "pydantic", "redis", "uvicorn")},
            "passed_requests": len(results),
            "requests": results,
            "sql_injection": {
                "search_payloads_per_user": len(payloads),
                "users_tested": [1, 2],
                "before": before_probes,
                "after": after_probes,
                "database_unchanged": True,
                "conclusion": "SQL-инъекция проверенными запросами не подтверждена. Все ожидаемые ответы получены; данные до и после проб совпали.",
                "timing_note": "Время ответов приведено для наблюдения; отдельный вывод об отсутствии SQL-инъекции по скорости не делается.",
            },
            "identity_spoofing": {
                "foreign_owner_rejected": 403,
                "forged_identity": 1,
                "visible_transaction_ids": transaction_ids(forged_rows),
                "created_transaction_id": forged_transfer["transaction_id"],
                "after": after_forgery,
                "conclusion": "Сервер принимает произвольный X-User-Id без подтверждения личности. Это подмена личности с доступом к чужим объектам, а не SQL-инъекция.",
            },
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        await cache.aclose()
        await conn.close()


asyncio.run(main())
