"""Aggregator router for the v1 API surface."""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    agent_runs,
    auth,
    chat,
    chunks,
    citations,
    concept_graph,
    conversations,
    courses,
    dashboard,
    error_logs,
    general_error_logs,
    health,
    knowledge_points,
    llm_configs,
    materials,
    material_overview,
    parse,
    plans,
    quizzes,
    search,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(courses.router, prefix="/courses", tags=["courses"])
api_router.include_router(materials.router, prefix="/courses", tags=["materials"])
api_router.include_router(
    knowledge_points.router, prefix="/courses", tags=["knowledge_points"]
)
api_router.include_router(
    quizzes.weak_points_router, prefix="/courses", tags=["weak_points"]
)
api_router.include_router(parse.router, prefix="/materials", tags=["materials"])
api_router.include_router(
    material_overview.router, prefix="/materials", tags=["materials"]
)
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(
    conversations.router, prefix="/conversations", tags=["conversations"]
)
api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(citations.router, prefix="/messages", tags=["citations"])
api_router.include_router(chunks.router, prefix="/chunks", tags=["chunks"])
api_router.include_router(plans.router, prefix="/plans", tags=["plans"])
api_router.include_router(plans.todos_router, prefix="/todos", tags=["todos"])
api_router.include_router(quizzes.router, prefix="/quizzes", tags=["quizzes"])
api_router.include_router(agent_runs.router, prefix="/agent-runs", tags=["agent_runs"])
api_router.include_router(
    llm_configs.router, prefix="/llm-configs", tags=["llm_configs"]
)
api_router.include_router(
    dashboard.router, prefix="/dashboard", tags=["dashboard"]
)
api_router.include_router(
    error_logs.router, prefix="/agent-error-logs", tags=["error_logs"]
)
api_router.include_router(
    general_error_logs.router, prefix="/logs", tags=["logs"]
)
api_router.include_router(
    concept_graph.router, prefix="/concept-graph", tags=["concept_graph"]
)

__all__ = ["api_router"]
