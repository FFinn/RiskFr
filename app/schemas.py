from pydantic import BaseModel, Field

class TransferRequest(BaseModel):
    from_account_id: int
    to_account_id: int
    amount_cents: int = Field(gt=0)

class TransactionOut(BaseModel):
    id: int
    from_account_id: int
    to_account_id: int
    amount_cents: int
    created_at: str
