"""Shared schema pieces (pagination, error envelope)."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Cursor-paginated response envelope. next_cursor is null on the final page."""

    model_config = ConfigDict(from_attributes=True)

    items: list[T]
    next_cursor: str | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    error: ErrorBody
