import uuid
from datetime import datetime

from pydantic import BaseModel


class SavedUrlCreate(BaseModel):
    name: str
    url: str
    description: str | None = None


class SavedUrlUpdate(BaseModel):
    name: str
    url: str
    description: str | None = None


class SavedUrlRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    url: str
    description: str | None
    created_at: datetime
    updated_at: datetime
