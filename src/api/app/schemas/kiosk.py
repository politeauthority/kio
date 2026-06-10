import uuid
from datetime import datetime

from pydantic import BaseModel


class KioskCreate(BaseModel):
    name: str
    hostname: str


class KioskUpdate(BaseModel):
    name: str | None = None
    hostname: str | None = None
    features: list[str] | None = None


class KioskRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    hostname: str
    current_url: str | None
    status: str
    last_seen: datetime | None
    features: list[str]
    device_type: str | None
    ip_address: str | None
    current_input: str | None
    display_on: bool | None
    agent_version: str | None
    uptime_seconds: int | None
    uptime_reported_at: datetime | None
    playlist_id: uuid.UUID | None
    meta: dict
    browser_flags: list[str]
    browser_tabs: list[dict]
    playlist_state: dict | None
    created_at: datetime
    updated_at: datetime
