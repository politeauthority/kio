import uuid
from datetime import datetime

from pydantic import BaseModel


class NodeTokenCreate(BaseModel):
    description: str | None = None


class NodeTokenCreated(BaseModel):
    id: uuid.UUID
    token: str
    description: str | None
    created_at: datetime


class NodeTokenRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    kiosk_id: uuid.UUID
    description: str | None
    created_at: datetime
    last_used_at: datetime | None
