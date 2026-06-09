
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.database import get_session
from app.models.kiosk import Kiosk
from app.models.node_token import NodeToken

_bearer = HTTPBearer()


async def get_node_kiosk(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Kiosk:
    token_hash = NodeToken.hash(credentials.credentials)

    result = await session.execute(select(NodeToken).where(NodeToken.token_hash == token_hash))
    node_token = result.scalar_one_or_none()

    if node_token is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    await session.execute(update(NodeToken).where(NodeToken.id == node_token.id).values(last_used_at=func.now()))

    kiosk = await session.get(Kiosk, node_token.kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    return kiosk
