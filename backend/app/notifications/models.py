from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, IdMixin, TimestampedTenantMixin


class Notification(TimestampedTenantMixin, Base):
    """An in-app notification for one user (spec §14). organization_id is the recipient's organization."""

    __tablename__ = "notifications"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(300))
    engagement_id: Mapped[str | None] = mapped_column(String(36), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)


class DailyJobRun(IdMixin, Base):
    """One run of the daily jobs (11-10 review O7). The unique date is the claim: the run happens once a day, at 10:00
    UTC or the first time the app is open after that, and a second process that finds the day taken runs nothing."""

    __tablename__ = "daily_job_runs"
    __table_args__ = (UniqueConstraint("run_on", name="uq_daily_job_run_on"),)

    run_on: Mapped[date] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10), default="running")  # running | completed | failed (one job or more failed)
    outcome: Mapped[dict] = mapped_column(JSON, default=dict)  # what each job returned
