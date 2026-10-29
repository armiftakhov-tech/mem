"""Общая предметная логика: аудит, уведомления, напоминания, повторы, сериализация."""

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import timeutil
from app.models import (
    Assignment,
    AssignmentReview,
    AuditEvent,
    Child,
    ChildMark,
    Comment,
    Discussion,
    Family,
    Notification,
    NotificationSettings,
    Parent,
    Recurrence,
    Reminder,
    new_id,
    utcnow,
)

log = logging.getLogger(__name__)

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
OUTCOME_TEXT = {"done": "выполнено", "partial": "частично", "not_done": "не выполнено"}


# ---------- аудит и уведомления ----------


def audit(
    db: Session,
    *,
    family_id: str | None,
    actor_account_id: str | None,
    entity_type: str,
    entity_id: str | None,
    event_type: str,
    payload: dict | None = None,
) -> AuditEvent:
    ev = AuditEvent(
        id=new_id(),
        family_id=family_id,
        actor_account_id=actor_account_id,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        payload=payload or {},
    )
    db.add(ev)
    db.flush()
    return ev


def _settings(db: Session, parent_id: str) -> NotificationSettings:
    s = db.get(NotificationSettings, parent_id)
    if s is None:
        s = NotificationSettings(parent_id=parent_id)
        db.add(s)
        db.flush()
    return s


def notify_parents(
    db: Session,
    *,
    family_id: str,
    type: str,
    text: str,
    dedup_key: str,
    assignment_id: str | None = None,
    reminder_id: str | None = None,
    exclude_parent_id: str | None = None,
) -> int:
    """Создаёт уведомления активным родителям. Повтор с тем же dedup_key — no-op."""
    parents = db.scalars(select(Parent).where(Parent.family_id == family_id, Parent.status == "active")).all()
    created = 0
    for p in parents:
        if p.id == exclude_parent_id:
            continue
        s = _settings(db, p.id)
        if type == "reminder" and not s.reminders_enabled:
            continue
        if type != "reminder" and not s.changes_enabled:
            continue
        exists = db.scalar(
            select(Notification.id).where(Notification.parent_id == p.id, Notification.dedup_key == dedup_key)
        )
        if exists:
            continue
        db.add(
            Notification(
                parent_id=p.id,
                type=type,
                text=text,
                dedup_key=dedup_key,
                assignment_id=assignment_id,
                reminder_id=reminder_id,
            )
        )
        created += 1
    db.flush()
    return created


def notify_change(db: Session, *, ev: AuditEvent, type: str, text: str, assignment_id: str, exclude_parent_id):
    notify_parents(
        db,
        family_id=ev.family_id,
        type=type,
        text=text,
        dedup_key=f"{type}:{ev.id}",
        assignment_id=assignment_id,
        exclude_parent_id=exclude_parent_id,
    )


# ---------- напоминания ----------


def schedule_reminder(db: Session, a: Assignment) -> None:
    """Отменяет будущие напоминания задания и ставит новое на check_at (docs/02 §14)."""
    db.execute(
        update(Reminder)
        .where(Reminder.assignment_id == a.id, Reminder.status == "scheduled")
        .values(status="cancelled")
    )
    if a.state == "active":
        db.add(Reminder(assignment_id=a.id, scheduled_at=a.check_at))
    db.flush()


def cancel_reminders(db: Session, assignment_id: str) -> None:
    db.execute(
        update(Reminder)
        .where(Reminder.assignment_id == assignment_id, Reminder.status == "scheduled")
        .values(status="cancelled")
    )


def process_due_reminders(db: Session, now: datetime | None = None) -> int:
    """Обрабатывает созревшие напоминания ровно один раз, в том числе пропущенные при выключении.

    TODO(open-question): AGENTS.md §31 п.3–4 — после долгого простоя или скачка часов
    сейчас отправляется по одному уведомлению на каждое пропущенное напоминание.
    """
    now = now or utcnow()
    due = db.scalars(
        select(Reminder).where(Reminder.status == "scheduled", Reminder.scheduled_at <= now).limit(200)
    ).all()
    for r in due:
        a = db.get(Assignment, r.assignment_id)
        r.status = "processed"
        r.processed_at = now
        if a is None or a.state != "active":
            continue
        child = db.get(Child, a.child_id)
        tz = db.get(Family, a.family_id).timezone
        notify_parents(
            db,
            family_id=a.family_id,
            type="reminder",
            text=f"Пора проверить: {a.text} · {child.name} · {timeutil.local(a.check_at, tz):%H:%M}",
            dedup_key=f"reminder:{r.id}",
            assignment_id=a.id,
            reminder_id=r.id,
        )
        audit(
            db,
            family_id=a.family_id,
            actor_account_id=None,
            entity_type="reminder",
            entity_id=r.id,
            event_type="processed",
        )
    if due:
        log.info("reminders processed: %d", len(due))
    return len(due)


# ---------- повторы ----------


def weekday_on(mask: int, day: date) -> bool:
    return bool(mask & (1 << day.weekday()))


def weekdays_text(mask: int) -> str:
    if mask == 0b1111111:
        return "ежедневно"
    if mask == 0b0011111:
        return "пн–пт"
    return ", ".join(d for i, d in enumerate(WEEKDAYS) if mask & (1 << i))


def generate_for_recurrence(db: Session, r: Recurrence, day: date, tz: str) -> Assignment | None:
    """Порождает задание на день. Ключ (recurrence_id, occurrence_date) защищает от дублей."""
    if r.status != "active" or not weekday_on(r.weekdays, day):
        return None
    if day < r.starts_on or (r.ends_on and day > r.ends_on):
        return None
    if db.scalar(
        select(Assignment.id).where(Assignment.recurrence_id == r.id, Assignment.occurrence_date == day)
    ):
        return None
    a = Assignment(
        id=new_id(),
        family_id=r.family_id,
        child_id=r.child_id,
        created_by_parent_id=r.created_by_parent_id,
        recurrence_id=r.id,
        occurrence_date=day,
        text=r.text,
        success_criteria=r.success_criteria,
        due_at=timeutil.to_utc(day, r.due_local_time, tz),
        check_at=timeutil.to_utc(day, r.check_local_time, tz),
        idempotency_key=f"rec:{r.id}:{day.isoformat()}",
    )
    try:
        with db.begin_nested():
            db.add(a)
            db.flush()
    except IntegrityError:
        return None
    schedule_reminder(db, a)
    audit(
        db,
        family_id=r.family_id,
        actor_account_id=None,
        entity_type="assignment",
        entity_id=a.id,
        event_type="generated",
        payload={"recurrence_id": r.id, "date": day.isoformat()},
    )
    return a


def generate_today(db: Session, now: datetime | None = None) -> int:
    """Задания из повторов только на сегодня по зоне семьи; задним числом — нет (AGENTS.md §18)."""
    created = 0
    for fam in db.scalars(select(Family)).all():
        day = timeutil.today(fam.timezone, now)
        for r in db.scalars(
            select(Recurrence).where(Recurrence.family_id == fam.id, Recurrence.status == "active")
        ).all():
            if generate_for_recurrence(db, r, day, fam.timezone):
                created += 1
    if created:
        log.info("assignments generated from recurrences: %d", created)
    return created


# ---------- сериализация ----------


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def current_review(db: Session, assignment_id: str) -> AssignmentReview | None:
    return db.scalar(
        select(AssignmentReview).where(
            AssignmentReview.assignment_id == assignment_id, AssignmentReview.is_current.is_(True)
        )
    )


def assignment_out(db: Session, a: Assignment, tz: str, *, detail: bool = False, for_child: bool = False) -> dict:
    now = utcnow()
    child = db.get(Child, a.child_id)
    author = db.get(Parent, a.created_by_parent_id)
    rec = db.get(Recurrence, a.recurrence_id) if a.recurrence_id else None
    cur = current_review(db, a.id)
    mark = db.get(ChildMark, a.id)
    disc = db.scalar(select(Discussion).where(Discussion.assignment_id == a.id))
    comments_count = (
        db.scalar(
            select(func.count()).select_from(Comment).where(
                Comment.discussion_id == disc.id, Comment.deleted_at.is_(None)
            )
        )
        if disc
        else 0
    )
    due_l, check_l = timeutil.local(a.due_at, tz), timeutil.local(a.check_at, tz)
    out = {
        "id": a.id,
        "child_id": a.child_id,
        "child_name": child.name,
        "text": a.text,
        "success_criteria": a.success_criteria,
        "due_at": _iso(a.due_at),
        "check_at": _iso(a.check_at),
        "date": check_l.date().isoformat(),
        "due_time": f"{due_l:%H:%M}",
        "check_time": f"{check_l:%H:%M}",
        "state": a.state,
        "overdue": a.state == "active" and now > a.check_at,
        "due_passed": now >= a.due_at,
        "version": a.version,
        "recurrence_id": a.recurrence_id,
        "recurrence_text": weekdays_text(rec.weekdays) if rec else None,
        "created_by_name": author.name if author else None,
        "closed_at": _iso(a.closed_at),
        "cancelled_at": _iso(a.cancelled_at),
        "current_review": review_out(db, cur) if cur else None,
        "child_marked_at": _iso(mark.marked_at) if mark else None,
        "comments_count": comments_count,
    }
    if a.cancelled_by_parent_id:
        out["cancelled_by_name"] = db.get(Parent, a.cancelled_by_parent_id).name
    if detail:
        reviews = db.scalars(
            select(AssignmentReview)
            .where(AssignmentReview.assignment_id == a.id)
            .order_by(AssignmentReview.reviewed_at)
        ).all()
        out["reviews"] = [review_out(db, r) for r in reviews]
        out["comments"] = []
        if disc:
            for c in db.scalars(
                select(Comment)
                .where(Comment.discussion_id == disc.id, Comment.deleted_at.is_(None))
                .order_by(Comment.created_at)
            ).all():
                author_name = (
                    db.get(Parent, c.author_parent_id).name if c.author_parent_id else db.get(Child, c.author_child_id).name
                )
                out["comments"].append(
                    {
                        "id": c.id,
                        "text": c.text,
                        "author_name": author_name,
                        "by_child": c.author_child_id is not None,
                        "created_at": _iso(c.created_at),
                    }
                )
    return out


def review_out(db: Session, r: AssignmentReview) -> dict:
    return {
        "id": r.id,
        "outcome": r.outcome,
        "is_current": r.is_current,
        "reviewer_name": db.get(Parent, r.reviewer_parent_id).name,
        "reviewed_at": _iso(r.reviewed_at),
        "corrects": r.supersedes_review_id is not None,
    }


def ensure_discussion(db: Session, assignment_id: str) -> Discussion:
    disc = db.scalar(select(Discussion).where(Discussion.assignment_id == assignment_id))
    if disc is None:
        disc = Discussion(assignment_id=assignment_id)
        db.add(disc)
        db.flush()
    return disc


def recurrence_out(r: Recurrence) -> dict:
    return {
        "id": r.id,
        "child_id": r.child_id,
        "text": r.text,
        "success_criteria": r.success_criteria,
        "weekdays": r.weekdays,
        "weekdays_text": weekdays_text(r.weekdays),
        "due_time": f"{r.due_local_time:%H:%M}",
        "check_time": f"{r.check_local_time:%H:%M}",
        "starts_on": r.starts_on.isoformat(),
        "ends_on": r.ends_on.isoformat() if r.ends_on else None,
        "status": r.status,
        "version": r.version,
    }


def history_window(tz: str, period: str, now: datetime | None = None) -> datetime | None:
    if period == "all":
        return None
    days = {"week": 7, "month": 30}.get(period, 7)
    start_day = timeutil.today(tz, now) - timedelta(days=days - 1)
    return timeutil.day_bounds_utc(start_day, tz)[0]
