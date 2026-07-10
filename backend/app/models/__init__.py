"""ORM models package.

Concrete models are imported here so that ``Base.metadata`` collects
every table for ``init_db`` / Alembic.
"""
from app.models.audit import AgentRun, AgentStep
from app.models.base import Base, TimestampMixin
from app.models.citation import Citation
from app.models.concept_graph import (
    ConceptCompareReport,
    ConceptEdge,
    ConceptNode,
)
from app.models.conversation import Conversation, Message
from app.models.course import Course
from app.models.error_log import AgentErrorLog
from app.models.general_error_log import ErrorLog
from app.models.knowledge_point import KnowledgePoint
from app.models.llm_config import UserLLMConfig
from app.models.material import Material, MaterialVersion
from app.models.material_chunk import MaterialChunk
from app.models.material_image import MaterialImage
from app.models.plan import StudyGoal, StudyTask, Todo
from app.models.quiz import Quiz, QuizItem, WeakPoint
from app.models.security_finding import MaterialSecurityFinding
from app.models.user import User

__all__ = [
    "Base",
    "TimestampMixin",
    "AgentRun",
    "AgentStep",
    "AgentErrorLog",
    "ErrorLog",
    "Citation",
    "ConceptCompareReport",
    "ConceptEdge",
    "ConceptNode",
    "Conversation",
    "Message",
    "Course",
    "KnowledgePoint",
    "Material",
    "MaterialVersion",
    "MaterialChunk",
    "MaterialImage",
    "MaterialSecurityFinding",
    "StudyGoal",
    "StudyTask",
    "Todo",
    "Quiz",
    "QuizItem",
    "WeakPoint",
    "User",
    "UserLLMConfig",
]
