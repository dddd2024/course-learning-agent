"""Security utilities: password hashing and JWT helpers.

Password hashing uses passlib's bcrypt scheme. JWTs are signed with
``settings.JWT_SECRET_KEY`` using ``settings.JWT_ALGORITHM`` and expire
after ``settings.ACCESS_TOKEN_EXPIRE_MINUTES`` minutes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Return a bcrypt hash for the given plain password."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if ``plain`` matches the previously hashed password."""
    return pwd_context.verify(plain, hashed)


def create_access_token(data: Dict[str, Any]) -> str:
    """Encode ``data`` into a signed JWT with an ``exp`` claim.

    A shallow copy of ``data`` is made so the caller's dict is not
    mutated. The ``exp`` claim is set to now + ACCESS_TOKEN_EXPIRE_MINUTES.
    """
    to_encode = dict(data)
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode["exp"] = expire
    return jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and verify a JWT, returning its payload.

    Raises ``JWTError`` (from python-jose) if the token is invalid,
    expired, or has a bad signature.
    """
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as exc:
        raise JWTError(f"invalid token: {exc}") from exc
