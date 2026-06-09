import uuid
from datetime import datetime

from pydantic import BaseModel


class CertificateCreate(BaseModel):
    name: str
    description: str | None = None
    content: str


class CertificateRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    content: str
    created_at: datetime
    updated_at: datetime
