"""Schemas shared across API endpoints."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response returned by the health endpoint."""

    status: Literal["ok"]
    application: str
    version: str
