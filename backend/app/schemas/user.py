"""Pydantic schemas for the auth endpoints."""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


def mask_email(email: str | None) -> str | None:
    """Mask an email address for display (security Task C1).

    ``alice@example.com`` -> ``a***@e***.com``. The local-part keeps its
    first char; the domain keeps its first char and the TLD. ``None`` and
    empty strings are returned unchanged so nullable columns stay nullable.
    Username (login) is intentionally NOT masked — it is needed for login
    and indexing.
    """
    if not email:
        return email
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if not local or not domain:
        return email
    masked_local = f"{local[0]}***"
    if "." in domain:
        dom_name, _, tld = domain.rpartition(".")
        if dom_name:
            masked_domain = f"{dom_name[0]}***.{tld}"
        else:
            masked_domain = f"{domain[0]}***.{tld}"
    else:
        masked_domain = f"{domain[0]}***"
    return f"{masked_local}@{masked_domain}"


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
    """User fields returned by register / me.

    Security Task C1: ``email_masked`` exposes a redacted form of the
    email for display. The raw ``email`` field is retained for backward
    compatibility but frontend surfaces should prefer ``email_masked``.
    """

    user_id: int
    username: str
    email: str | None = None
    email_masked: str | None = None

    @model_validator(mode="after")
    def _fill_email_masked(self) -> "UserResponse":
        if self.email_masked is None and self.email is not None:
            self.email_masked = mask_email(self.email)
        return self


class TokenResponse(BaseModel):
    """Token envelope returned by login."""

    access_token: str
    token_type: str = "bearer"


class SecurityStatusResponse(BaseModel):
    """Security posture reported by GET /auth/security-status (Task F).

    Surfaces how credentials are stored and whether the running env is
    using a default secret, so the profile page can render a security
    status card. ``using_default_secret`` is only meaningful (and only
    surfaced as True) in development; production refuses to start with a
    default secret, so the flag is always False there.
    """

    password_storage: str
    api_key_storage: str
    token_expiry_minutes: int
    environment: str
    using_default_secret: bool
