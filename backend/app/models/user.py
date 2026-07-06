"""User ORM model."""
from sqlalchemy import Column, Integer, String

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """A registered platform user."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(100))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User id={self.id} username={self.username!r}>"
