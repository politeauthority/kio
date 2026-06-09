import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PlaylistItemIn(BaseModel):
    title: str | None = None
    url: str
    duration_seconds: int = Field(default=30, ge=1)
    position: int = 0


class PlaylistItemRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str | None
    url: str
    duration_seconds: int
    position: int


class PlaylistCreate(BaseModel):
    name: str
    description: str | None = None
    refresh_interval_seconds: int = Field(default=0, ge=0)


class PlaylistRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    refresh_interval_seconds: int
    created_at: datetime
    updated_at: datetime


class PlaylistReadWithCount(PlaylistRead):
    item_count: int = 0


class PlaylistDetail(PlaylistRead):
    items: list[PlaylistItemRead] = []


class PlaylistUpdate(BaseModel):
    name: str
    description: str | None = None
    refresh_interval_seconds: int = Field(default=0, ge=0)
    items: list[PlaylistItemIn] = []
