import os

from sqlalchemy import String, Text, create_engine
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
    # PENDING, PROCESSING, COMPLETED, FAILED
    status: Mapped[str] = mapped_column(String, default="PENDING")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
