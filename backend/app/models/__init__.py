"""ORM models package.

Concrete models are imported here so that ``Base.metadata`` collects
every table for ``init_db`` / Alembic.
"""
from app.models.audit import AgentRun, AgentStep
from app.models.base import Base, TimestampMixin
from app.models.citation import Citation
from app.models.conversation import Conversation, Message
from app.models.course import Course
from app.models.knowledge_point import KnowledgePoint
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.plan import StudyGoal, StudyTask, Todo
from app.models.quiz import Quiz, QuizItem, WeakPoint
from app.models.user import User

__all__ = [
    "Base",
    "TimestampMixin",
    "AgentRun",
    "AgentStep",
    "Citation",
    "Conversation",
    "Message",
    "Course",
    "KnowledgePoint",
    "Material",
    "MaterialChunk",
    "StudyGoal",
    "StudyTask",
    "Todo",
    "Quiz",
    "QuizItem",
    "WeakPoint",
    "User",
]
