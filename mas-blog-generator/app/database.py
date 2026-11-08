import os
from datetime import datetime

from sqlalchemy import DateTime, String, Text, create_engine, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:password@localhost:5432/mas_db"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


class TaskLog(Base):
    __tablename__ = "task_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # Celery task ID
    topic: Mapped[str] = mapped_column(String, index=True)
    # PENDING, PROCESSING, COMPLETED, FAILED, CANCELLING, CANCELLED
    status: Mapped[str] = mapped_column(String, default="PENDING")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    # create_all does not add columns to a table that already exists.
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE task_logs ADD COLUMN IF NOT EXISTS"
                " created_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_task_logs_created_at"
                " ON task_logs (created_at)"
            )
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
