"""Common FastAPI dependencies shared across endpoints."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User

# auto_error=False so missing/invalid auth yields a 401 from our handler
# instead of FastAPI's default 403.
_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the Authorization Bearer token.

    Raises 401 if the header is missing, malformed, the JWT cannot be
    decoded, or the referenced user no longer exists.
    """
    _unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None or (credentials.scheme or "").lower() != "bearer":
        raise _unauthorized

    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError:
        raise _unauthorized

    subject = payload.get("sub")
    if subject is None:
        raise _unauthorized

    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise _unauthorized

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise _unauthorized

    return user


__all__ = ["get_db", "get_current_user"]
