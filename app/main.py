from fastapi import FastAPI, Depends, Query
from app.db import init_db
from app.security import get_current_user_id
from app.schemas import TransferRequest, TransactionOut
from app import crud

app = FastAPI(title="Bank Microservice")

@app.on_event("startup")
async def _startup():
    await init_db()

@app.post("/transfer")
async def do_transfer(req: TransferRequest, uid: int = Depends(get_current_user_id)):
    tx_id = await crud.transfer(uid, req.from_account_id, req.to_account_id, req.amount_cents)
    return {"status": "ok", "transaction_id": tx_id}

@app.get("/transactions", response_model=list[TransactionOut])
async def txs(
    uid: int = Depends(get_current_user_id),
    limit: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=100),
):
    rows = await crud.list_transactions(uid, limit, search)
    return [
        TransactionOut(
            id=r["id"],
            from_account_id=r["from_account_id"],
            to_account_id=r["to_account_id"],
            amount_cents=r["amount_cents"],
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]
