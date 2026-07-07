"""FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers

# T09: validate production secrets at import time so a misconfigured
# production deployment fails fast instead of silently running with
# default keys.
settings.validate_prod_secrets()

app = FastAPI(
    title="Course Learning Assistant API",
    description="课程学习助手 Agent 平台后端",
    version="0.1.0",
)

# T09: CORS origins are now driven by the CORS_ORIGINS env var instead
# of a hardcoded "*". The default allows localhost:5173 (Vite dev
# server); production deployments should set CORS_ORIGINS to the
# real frontend origin(s).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(api_router, prefix="/api/v1")
