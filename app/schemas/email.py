"""Provider-neutral email response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class EmailSummary(BaseModel):
    id: str
    sender_name: str | None
    sender_email: str | None
    subject: str | None
    received_at: datetime
    has_attachments: bool


class EmailListResponse(BaseModel):
    provider: Literal["outlook", "gmail"]
    emails: list[EmailSummary]
