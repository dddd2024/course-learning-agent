"""Authentication endpoints: register, login, me."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import _DEFAULT_LLM_CONFIG_SECRET, settings
from app.core.database import get_db
from app.core.exceptions import InvalidCredentialsException, UsernameExistsException
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.user import (
    SecurityStatusResponse,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    mask_email,
)

router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> UserResponse:
    """Register a new user. Returns 400 USERNAME_EXISTS on conflict."""
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing is not None:
        raise UsernameExistsException()

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        email=payload.email,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return UserResponse(
        user_id=user.id,
        username=user.username,
        email_masked=mask_email(user.email),
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> TokenResponse:
    """Authenticate and return a JWT. Returns 401 on bad credentials."""
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise InvalidCredentialsException()

    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the profile of the authenticated user."""
    return UserResponse(
        user_id=current_user.id,
        username=current_user.username,
        email_masked=mask_email(current_user.email),
    )


@router.get("/security-status", response_model=SecurityStatusResponse)
def security_status(
    current_user: User = Depends(get_current_user),
) -> SecurityStatusResponse:
    """Return the platform's security posture for the profile card.

    Security Task F: surfaces how credentials are stored (bcrypt hash,
    Fernet-encrypted API keys), the token expiry, the running
    environment, and whether a default secret is in use (only surfaced
    in development — production refuses to start with a default secret).
    """
    is_prod = settings.ENVIRONMENT.lower() == "production"
    using_default = (
        not is_prod
        and settings.LLM_CONFIG_SECRET_KEY == _DEFAULT_LLM_CONFIG_SECRET
    )
    return SecurityStatusResponse(
        password_storage="bcrypt_hash",
        api_key_storage="fernet_encrypted",
        token_expiry_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        environment=settings.ENVIRONMENT,
        using_default_secret=using_default,
    )
