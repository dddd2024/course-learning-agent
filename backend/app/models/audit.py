"""Agent execution audit ORM models.

An ``AgentRun`` records one invocation of an agent (``course_qa`` /
``outline`` / ``planner`` / ``quiz``) along with its inputs, outputs,
prompt version, and timing. Each run is broken down into one or more
``AgentStep`` rows (``retrieve`` / ``rerank`` / ``generate`` /
``validate`` / ``persist`` ...) so the operator can replay the agent
trace and audit cost / latency / failures.

Both tables are scoped by ``user_id`` so cross-user access is invisible
(returned as 404) by the API layer.
"""
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin


class AgentRun(Base, TimestampMixin):
    """A single agent execution traced for audit / statistics."""

    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    # course_qa / outline / planner / quiz
    run_type = Column(String(30), nullable=False, index=True)
    # running / success / failed
    status = Column(String(20), default="running", nullable=False)
    # JSON-serialised input summary (truncated long text).
    input_summary = Column(Text)
    # JSON-serialised output summary (truncated long text).
    output_summary = Column(Text)
    prompt_version = Column(String(50))
    model_name = Column(String(50))
    duration_ms = Column(Integer, nullable=True)
    error_message = Column(Text)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    steps = relationship(
        "AgentStep",
        backref="run",
        cascade="all, delete-orphan",
        order_by="AgentStep.step_index",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<AgentRun id={self.id} run_type={self.run_type!r} "
            f"status={self.status!r} user_id={self.user_id}>"
        )


class AgentStep(Base, TimestampMixin):
    """A single step within an ``AgentRun`` trace."""

    __tablename__ = "agent_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(
        Integer,
        ForeignKey("agent_runs.id"),
        nullable=False,
        index=True,
    )
    # retrieve / rerank / generate / validate / persist ...
    step_name = Column(String(50), nullable=False)
    step_index = Column(Integer, nullable=False, default=0)
    # JSON-serialised step input.
    input_data = Column(Text)
    # JSON-serialised step output.
    output_data = Column(Text)
    duration_ms = Column(Integer, nullable=True)
    # success / failed
    status = Column(String(20), default="success", nullable=False)
    error_message = Column(Text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<AgentStep id={self.id} run_id={self.run_id} "
            f"step_name={self.step_name!r} status={self.status!r}>"
        )
