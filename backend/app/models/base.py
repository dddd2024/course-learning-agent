"""Declarative base and shared ORM mixins."""
from sqlalchemy import DateTime, func
from sqlalchemy.orm import declarative_base, declared_attr, mapped_column


class TimestampMixin:
    """Mixin providing ``created_at`` / ``updated_at`` columns."""

    @declared_attr
    def created_at(cls):  # noqa: N805 - SQLAlchemy mixin convention
        return mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )

    @declared_attr
    def updated_at(cls):  # noqa: N805 - SQLAlchemy mixin convention
        return mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )


Base = declarative_base()
