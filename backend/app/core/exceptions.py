"""Unified exception handling and custom business exceptions.

All error responses share the shape::

    {"code": "ERROR_CODE", "message": "human readable text"}

so the frontend can branch on ``code`` and display ``message`` directly.
"""
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppException(Exception):
    """Base class for business-layer exceptions.

    Subclasses set ``code`` and the default ``status_code``.
    """

    code: str = "BUSINESS_ERROR"
    status_code: int = 400
    default_message: str = "业务错误"

    def __init__(self, message: str | None = None, status_code: int | None = None):
        self.message = message or self.default_message
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.message)


class NotFoundException(AppException):
    code = "NOT_FOUND"
    status_code = 404
    default_message = "资源不存在"


class ForbiddenException(AppException):
    code = "FORBIDDEN"
    status_code = 403
    default_message = "无权访问"


class BusinessException(AppException):
    code = "BUSINESS_ERROR"
    status_code = 400
    default_message = "业务错误"


class UsernameExistsException(BusinessException):
    code = "USERNAME_EXISTS"
    default_message = "用户名已存在"


class InvalidCredentialsException(AppException):
    code = "INVALID_CREDENTIALS"
    status_code = 401
    default_message = "用户名或密码错误"


def _error_body(code: str, message: str) -> Dict[str, Any]:
    return {"code": code, "message": message}


def register_exception_handlers(app: FastAPI) -> None:
    """Register the unified exception handlers on ``app``."""

    @app.exception_handler(AppException)
    async def handle_app_exception(_: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "请求错误"
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body("HTTP_ERROR", detail),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_body("VALIDATION_ERROR", str(exc.errors())),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(_: Request, exc: Exception) -> JSONResponse:
        # HTTPException raised explicitly is still routed here as a fallback.
        if isinstance(exc, HTTPException):
            detail = exc.detail if isinstance(exc.detail, str) else "请求错误"
            return JSONResponse(
                status_code=exc.status_code,
                content=_error_body("HTTP_ERROR", detail),
            )
        return JSONResponse(
            status_code=500,
            content=_error_body("INTERNAL_ERROR", "服务器内部错误"),
        )
