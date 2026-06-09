import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.kiosk import Kiosk
from app.models.node_token import NodeToken
from app.schemas.node_token import NodeTokenCreate, NodeTokenCreated, NodeTokenRead

router = APIRouter(prefix="/kiosks/{kiosk_id}/tokens", tags=["tokens"])


async def _get_kiosk_or_404(kiosk_id: uuid.UUID, session: AsyncSession) -> Kiosk:
    kiosk = await session.get(Kiosk, kiosk_id)
    if kiosk is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    return kiosk


@router.get("", response_model=list[NodeTokenRead])
async def list_tokens(kiosk_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    await _get_kiosk_or_404(kiosk_id, session)
    result = await session.execute(
        select(NodeToken).where(NodeToken.kiosk_id == kiosk_id).order_by(NodeToken.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=NodeTokenCreated, status_code=201)
async def create_token(
    kiosk_id: uuid.UUID,
    data: NodeTokenCreate,
    session: AsyncSession = Depends(get_session),
):
    await _get_kiosk_or_404(kiosk_id, session)

    raw = f"kio_{secrets.token_urlsafe(32)}"
    token = NodeToken(
        id=uuid.uuid4(),
        kiosk_id=kiosk_id,
        token_hash=NodeToken.hash(raw),
        description=data.description,
    )
    session.add(token)
    await session.commit()
    await session.refresh(token)

    return NodeTokenCreated(
        id=token.id,
        token=raw,
        description=token.description,
        created_at=token.created_at,
    )


@router.delete("/{token_id}", status_code=204)
async def revoke_token(
    kiosk_id: uuid.UUID,
    token_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    await _get_kiosk_or_404(kiosk_id, session)
    result = await session.execute(
        delete(NodeToken).where(NodeToken.id == token_id).where(NodeToken.kiosk_id == kiosk_id)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Token not found")
    await session.commit()
