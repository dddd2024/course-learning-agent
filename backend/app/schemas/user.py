"""Pydantic schemas for the auth endpoints."""
from __future__ import annotations

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    """Payload for POST /auth/register."""

    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    email: str | None = Field(default=None, max_length=100)


class UserLogin(BaseModel):
    """Payload for POST /auth/login."""

    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    """User fields returned by register / me."""

    user_id: int
    username: str
    email: str | None = None


class TokenResponse(BaseModel):
    """Token envelope returned by login."""

    access_token: str
    token_type: str = "bearer"
