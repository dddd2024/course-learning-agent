"""FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.core.exceptions import register_exception_handlers

app = FastAPI(
    title="Course Learning Assistant API",
    description="课程学习助手 Agent 平台后端",
    version="0.1.0",
)

# CORS: allow all origins so the frontend can talk to the API during
# development. Tighten this before production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(api_router, prefix="/api/v1")
