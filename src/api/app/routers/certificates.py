import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.certificate import Certificate
from app.models.kiosk import Kiosk
from app.routers.kiosks import dispatch_command
from app.schemas.certificate import CertificateCreate, CertificateRead

router = APIRouter(prefix="/settings/certificates", tags=["certificates"])


@router.get("", response_model=list[CertificateRead])
async def list_certificates(session: AsyncSession = Depends(get_session)):
    rows = await session.execute(select(Certificate).order_by(Certificate.name))
    return [CertificateRead.model_validate(r) for r in rows.scalars().all()]


@router.post("", response_model=CertificateRead, status_code=201)
async def create_certificate(data: CertificateCreate, session: AsyncSession = Depends(get_session)):
    cert = Certificate(name=data.name, description=data.description, content=data.content.strip())
    session.add(cert)
    await session.commit()
    await session.refresh(cert)
    return CertificateRead.model_validate(cert)


@router.delete("/{cert_id}", status_code=204)
async def delete_certificate(cert_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    row = await session.get(Certificate, cert_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    await session.delete(row)
    # Push the revocation to nodes immediately — the agent's sync is declarative, so an
    # online kiosk drops the deleted cert from its trust store on this command. Offline
    # kiosks self-heal via the boot-time sync. Without this, deletion only removes the DB
    # row and the operator has to remember to click Sync for it to take effect.
    await _dispatch_sync_to_online_kiosks(session)
    await session.commit()


@router.post("/sync", status_code=204)
async def sync_certs_to_all_kiosks(session: AsyncSession = Depends(get_session)):
    await _dispatch_sync_to_online_kiosks(session)
    await session.commit()


async def _dispatch_sync_to_online_kiosks(session: AsyncSession) -> None:
    """Send sync_certs to all online kiosks, recording one event-log row per kiosk so
    the result (success or error) is auditable. dispatch_command tags each command with
    a CommandLog id that the agent echoes back when it acks. Caller commits."""
    kiosks = await session.execute(select(Kiosk).where(Kiosk.status == "online"))
    for kiosk in kiosks.scalars().all():
        dispatch_command(session, kiosk.id, command="sync_certs", payload={"command": "sync_certs"})
