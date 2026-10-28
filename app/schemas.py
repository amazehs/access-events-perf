"""Request and response models with input validation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal["unlock", "lock", "denied"]


class EventCreate(BaseModel):
    lock_id: str = Field(pattern=r"^LOCK-\d{4}$", examples=["LOCK-0042"])
    user_id: str = Field(pattern=r"^USER-\d{5}$", examples=["USER-01234"])
    event_type: EventType
    timestamp: datetime | None = Field(
        default=None, description="Event time; defaults to the server time when omitted."
    )


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lock_id: str
    user_id: str
    event_type: EventType
    timestamp: datetime


class Health(BaseModel):
    status: str
    variant: str
