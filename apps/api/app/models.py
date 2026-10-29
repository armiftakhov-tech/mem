"""Модель данных по docs/02-domain-model.md."""

import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """SQLite не хранит зону: пишем наивный UTC, читаем aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    type_annotation_map = {datetime: UTCDateTime, date: Date, time: Time, dict: JSON}


def pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=new_id)


def created() -> Mapped[datetime]:
    return mapped_column(default=utcnow)


class Account(Base):
    __tablename__ = "account"
    id: Mapped[str] = pk()
    login: Mapped[str] = mapped_column(String(254), unique=True)
    kind: Mapped[str] = mapped_column(String(10))
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(10), default="active")
    created_at: Mapped[datetime] = created()
    last_login_at: Mapped[datetime | None]
    __table_args__ = (
        CheckConstraint("kind IN ('parent','child')"),
        CheckConstraint("status IN ('active','blocked')"),
    )


class Session(Base):
    __tablename__ = "session"
    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"), index=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created()
    last_seen_at: Mapped[datetime] = created()
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]


class BootstrapToken(Base):
    __tablename__ = "bootstrap_token"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = created()
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]


class Family(Base):
    __tablename__ = "family"
    id: Mapped[str] = pk()
    name: Mapped[str | None] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created()


class Parent(Base):
    __tablename__ = "parent"
    id: Mapped[str] = pk()
    family_id: Mapped[str] = mapped_column(ForeignKey("family.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(10), default="active")
    created_at: Mapped[datetime] = created()
    __table_args__ = (CheckConstraint("status IN ('active','removed')"),)


class Child(Base):
    __tablename__ = "child"
    id: Mapped[str] = pk()
    family_id: Mapped[str] = mapped_column(ForeignKey("family.id"), index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("account.id"), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    birth_date: Mapped[date | None]
    created_at: Mapped[datetime] = created()


RELATION_TYPES = ("father", "mother", "guardian", "other")


class ParentChildRelation(Base):
    __tablename__ = "parent_child_relation"
    id: Mapped[str] = pk()
    parent_id: Mapped[str] = mapped_column(ForeignKey("parent.id"))
    child_id: Mapped[str] = mapped_column(ForeignKey("child.id", ondelete="CASCADE"))
    relation_type: Mapped[str] = mapped_column(String(10), default="other")
    status: Mapped[str] = mapped_column(String(10), default="active")
    created_at: Mapped[datetime] = created()
    __table_args__ = (UniqueConstraint("parent_id", "child_id"),)


class FamilyInvitation(Base):
    __tablename__ = "family_invitation"
    id: Mapped[str] = pk()
    family_id: Mapped[str] = mapped_column(ForeignKey("family.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    code_hint: Mapped[str] = mapped_column(String(8))
    created_by_parent_id: Mapped[str] = mapped_column(ForeignKey("parent.id"))
    created_at: Mapped[datetime] = created()
    expires_at: Mapped[datetime]
    accepted_by_account_id: Mapped[str | None] = mapped_column(ForeignKey("account.id"))
    accepted_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


class Recurrence(Base):
    __tablename__ = "recurrence"
    id: Mapped[str] = pk()
    family_id: Mapped[str] = mapped_column(ForeignKey("family.id"), index=True)
    child_id: Mapped[str] = mapped_column(ForeignKey("child.id"), index=True)
    created_by_parent_id: Mapped[str] = mapped_column(ForeignKey("parent.id"))
    text: Mapped[str] = mapped_column(Text)
    success_criteria: Mapped[str | None] = mapped_column(Text)
    weekdays: Mapped[int] = mapped_column(Integer)  # бит 0 = пн … бит 6 = вс
    due_local_time: Mapped[time]
    check_local_time: Mapped[time]
    starts_on: Mapped[date]
    ends_on: Mapped[date | None]
    status: Mapped[str] = mapped_column(String(10), default="active")
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()
    __table_args__ = (
        CheckConstraint("check_local_time >= due_local_time"),
        CheckConstraint("weekdays > 0 AND weekdays < 128"),
        CheckConstraint("status IN ('active','paused','ended')"),
    )


class Assignment(Base):
    __tablename__ = "assignment"
    id: Mapped[str] = pk()
    family_id: Mapped[str] = mapped_column(ForeignKey("family.id"), index=True)
    child_id: Mapped[str] = mapped_column(ForeignKey("child.id"), index=True)
    created_by_parent_id: Mapped[str] = mapped_column(ForeignKey("parent.id"))
    recurrence_id: Mapped[str | None] = mapped_column(ForeignKey("recurrence.id"))
    occurrence_date: Mapped[date | None]
    text: Mapped[str] = mapped_column(Text)
    success_criteria: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime]
    check_at: Mapped[datetime] = mapped_column(index=True)
    state: Mapped[str] = mapped_column(String(10), default="active")
    version: Mapped[int] = mapped_column(default=1)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()
    closed_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    cancelled_by_parent_id: Mapped[str | None] = mapped_column(ForeignKey("parent.id"))
    __table_args__ = (
        CheckConstraint("check_at >= due_at"),
        CheckConstraint("state IN ('active','closed','cancelled')"),
        CheckConstraint("(recurrence_id IS NULL) = (occurrence_date IS NULL)"),
        UniqueConstraint("recurrence_id", "occurrence_date"),
    )


class AssignmentReview(Base):
    __tablename__ = "assignment_review"
    id: Mapped[str] = pk()
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignment.id"), index=True)
    reviewer_parent_id: Mapped[str] = mapped_column(ForeignKey("parent.id"))
    outcome: Mapped[str] = mapped_column(String(10))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    supersedes_review_id: Mapped[str | None] = mapped_column(ForeignKey("assignment_review.id"))
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    reviewed_at: Mapped[datetime] = created()
    __table_args__ = (
        CheckConstraint("outcome IN ('done','partial','not_done')"),
        Index(
            "uq_review_current",
            "assignment_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
        ),
    )


class ChildMark(Base):
    __tablename__ = "child_mark"
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignment.id"), primary_key=True)
    child_id: Mapped[str] = mapped_column(ForeignKey("child.id"))
    marked_at: Mapped[datetime] = created()


class Discussion(Base):
    __tablename__ = "discussion"
    id: Mapped[str] = pk()
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignment.id"), unique=True)
    created_at: Mapped[datetime] = created()


class Comment(Base):
    __tablename__ = "comment"
    id: Mapped[str] = pk()
    discussion_id: Mapped[str] = mapped_column(ForeignKey("discussion.id"), index=True)
    author_parent_id: Mapped[str | None] = mapped_column(ForeignKey("parent.id"))
    author_child_id: Mapped[str | None] = mapped_column(ForeignKey("child.id"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    edited_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]
    __table_args__ = (CheckConstraint("(author_parent_id IS NULL) != (author_child_id IS NULL)"),)


class Reminder(Base):
    __tablename__ = "reminder"
    id: Mapped[str] = pk()
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignment.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="check_due")
    scheduled_at: Mapped[datetime]
    status: Mapped[str] = mapped_column(String(10), default="scheduled")
    processed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()
    __table_args__ = (Index("ix_reminder_due", "status", "scheduled_at"),)


class Notification(Base):
    __tablename__ = "notification"
    id: Mapped[str] = pk()
    parent_id: Mapped[str] = mapped_column(ForeignKey("parent.id"))
    type: Mapped[str] = mapped_column(String(30))
    assignment_id: Mapped[str | None] = mapped_column(ForeignKey("assignment.id"))
    reminder_id: Mapped[str | None] = mapped_column(ForeignKey("reminder.id"))
    text: Mapped[str] = mapped_column(Text)
    dedup_key: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = created()
    read_at: Mapped[datetime | None]
    __table_args__ = (
        UniqueConstraint("parent_id", "dedup_key"),
        Index("ix_notification_parent", "parent_id", "created_at"),
    )


class NotificationSettings(Base):
    __tablename__ = "notification_settings"
    parent_id: Mapped[str] = mapped_column(ForeignKey("parent.id"), primary_key=True)
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    changes_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    browser_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = created()


class AuditEvent(Base):
    __tablename__ = "audit_event"
    id: Mapped[str] = pk()
    family_id: Mapped[str | None] = mapped_column(ForeignKey("family.id"), index=True)
    actor_account_id: Mapped[str | None] = mapped_column(ForeignKey("account.id"))
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str | None] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(default=dict)
    occurred_at: Mapped[datetime] = created()


class ProcessedCommand(Base):
    __tablename__ = "processed_command"
    idempotency_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"), primary_key=True)
    command: Mapped[str] = mapped_column(String(50))
    response: Mapped[dict]
    created_at: Mapped[datetime] = created()


class LoginAttempt(Base):
    __tablename__ = "login_attempt"
    id: Mapped[str] = pk()
    login_normalized: Mapped[str] = mapped_column(String(254), index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("account.id"))
    ip: Mapped[str | None] = mapped_column(String(45), index=True)
    success: Mapped[bool] = mapped_column(Boolean)
    attempted_at: Mapped[datetime] = created()
