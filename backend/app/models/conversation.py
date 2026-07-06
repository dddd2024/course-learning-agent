"""Conversation and Message ORM models.

A conversation groups a user's Q&A exchange within a single course.
Messages store the user questions and assistant answers (including the
structured ``answer_json`` payload) so the full chat history can be
replayed.
"""
from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.models.base import Base, TimestampMixin


class Conversation(Base, TimestampMixin):
    """A chat conversation scoped to one user and one course."""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(
        Integer, ForeignKey("courses.id"), nullable=False, index=True
    )
    title = Column(String(255))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Conversation id={self.id} user_id={self.user_id} "
            f"course_id={self.course_id} title={self.title!r}>"
        )


class Message(Base, TimestampMixin):
    """A single message (user question or assistant answer) in a conversation."""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(
        Integer, ForeignKey("conversations.id"), nullable=False, index=True
    )
    role = Column(String(20), nullable=False)  # user / assistant
    content = Column(Text)  # 用户问题文本或回答文本
    answer_json = Column(Text)  # assistant 回答的完整结构化 JSON（序列化存储）

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Message id={self.id} conversation_id={self.conversation_id} "
            f"role={self.role!r}>"
        )
