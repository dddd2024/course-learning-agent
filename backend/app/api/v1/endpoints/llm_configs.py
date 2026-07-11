"""User LLM config CRUD + enable/active/test endpoints.

All queries are scoped by ``current_user.id`` so a config owned by
another user is invisible (returned as 404) so existence is never
leaked. The plaintext API key is never serialised: ``LLMConfigResponse``
exposes only ``api_key_masked`` via the ORM property.

Route ordering note: ``/active`` is declared before ``/{config_id}`` so
the literal path wins over the path parameter (otherwise "active" would
be parsed as a config id and fail int conversion).
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import BusinessException, NotFoundException
from app.models.user import User
from app.schemas.llm_config import (
    LLMConfigActiveResponse,
    LLMConfigCreate,
    LLMConfigListResponse,
    LLMConfigResponse,
    LLMConfigTestResponse,
    LLMConfigUpdate,
)
from app.services.llm_config_service import (
    create_config,
    delete_config,
    enable_config,
    get_active_config,
    get_config,
    get_user_configs,
    test_connection as _test_connection,
    update_config,
)

router = APIRouter()


def _get_owned_config(
    db: Session, config_id: int, user_id: int
) -> "UserLLMConfig":  # noqa: F821 - type-only hint
    """Return the config if it belongs to ``user_id``, else 404.

    Centralises the user-scoped lookup so isolation is consistent across
    PUT / DELETE / enable / test.
    """
    config = get_config(db, config_id, user_id)
    if config is None:
        raise NotFoundException(message="LLM 配置不存在")
    return config


@router.get("", response_model=LLMConfigListResponse)
def list_configs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LLMConfigListResponse:
    """List the current user's LLM configs."""
    configs = get_user_configs(db, current_user.id)
    return LLMConfigListResponse(
        items=[LLMConfigResponse.model_validate(c) for c in configs]
    )


@router.post("", response_model=LLMConfigResponse, status_code=201)
def create(
    payload: LLMConfigCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LLMConfigResponse:
    """Create a config bound to the authenticated user.

    The plaintext ``api_key`` is encrypted by the service layer before
    persistence; only the masked form is returned.
    """
    try:
        config = create_config(db, current_user.id, payload.model_dump())
    except ValueError as exc:
        raise BusinessException(message=str(exc)) from exc
    return LLMConfigResponse.model_validate(config)


@router.get("/active", response_model=LLMConfigActiveResponse)
def get_active(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LLMConfigActiveResponse:
    """Return the user's active (default) config, or ``config=null``."""
    config = get_active_config(db, current_user.id)
    if config is None:
        return LLMConfigActiveResponse(config=None)
    return LLMConfigActiveResponse(
        config=LLMConfigResponse.model_validate(config)
    )


@router.put("/{config_id}", response_model=LLMConfigResponse)
def update(
    config_id: int,
    payload: LLMConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LLMConfigResponse:
    """Update a config owned by the current user (404 otherwise)."""
    config = _get_owned_config(db, config_id, current_user.id)
    try:
        updated = update_config(db, config, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise BusinessException(message=str(exc)) from exc
    return LLMConfigResponse.model_validate(updated)


@router.delete("/{config_id}", status_code=204)
def delete(
    config_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete a config owned by the current user (404 otherwise)."""
    config = _get_owned_config(db, config_id, current_user.id)
    delete_config(db, config)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{config_id}/enable", response_model=LLMConfigResponse)
def enable(
    config_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LLMConfigResponse:
    """Mark a config as the user's default (mutual exclusivity)."""
    config = _get_owned_config(db, config_id, current_user.id)
    enabled = enable_config(db, config)
    return LLMConfigResponse.model_validate(enabled)


@router.post("/{config_id}/test", response_model=LLMConfigTestResponse)
def test(
    config_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LLMConfigTestResponse:
    """Probe the provider without mutating ``enabled`` state.

    Persists ``last_test_status`` / ``last_test_error`` / ``last_test_at``
    so the UI can surface the most recent result.
    """
    config = _get_owned_config(db, config_id, current_user.id)
    try:
        result = _test_connection(config)
    except ValueError as exc:
        raise BusinessException(message=str(exc)) from exc
    config.last_test_status = result["status"]
    config.last_test_error = result["error"]
    config.last_test_at = datetime.now()
    db.commit()
    db.refresh(config)
    return LLMConfigTestResponse(
        status=result["status"],
        error=result["error"],
        provider=result["provider"],
        model=result["model"],
    )
