from fastapi import Header, HTTPException

async def get_current_user_id(x_user_id: str | None = Header(default=None)) -> int:
    """
    УЧЕБНО: примитивная идентификация.
    В реальном проекте тут должен быть JWT/OAuth2 и т.д.
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id header")
    try:
        return int(x_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-User-Id")
