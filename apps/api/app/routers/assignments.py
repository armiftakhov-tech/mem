"""Задания, проверки, комментарии, отметка ребёнка, история, повторы."""

from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import timeutil
from app.deps import Actor, child_actor, conflict, current_actor, get_db, not_found, parent_actor
from app.models import (
    Assignment,
    AssignmentReview,
    Child,
    ChildMark,
    Comment,
    ProcessedCommand,
    Recurrence,
    new_id,
    utcnow,
)
from app.services import (
    OUTCOME_TEXT,
    assignment_out,
    audit,
    cancel_reminders,
    current_review,
    ensure_discussion,
    generate_for_recurrence,
    history_window,
    notify_change,
    notify_parents,
    recurrence_out,
    schedule_reminder,
)

router = APIRouter(tags=["assignments"])

Key = Field(min_length=8, max_length=64)


class TimesIn(BaseModel):
    due_time: time | None = None  # пусто — срок совпадает с проверкой
    check_time: time

    @model_validator(mode="after")
    def _order(self):
        if self.due_time is None:
            self.due_time = self.check_time
        if self.check_time < self.due_time:
            raise ValueError("Проверка не может быть раньше срока")
        return self


class AssignmentIn(TimesIn):
    idempotency_key: str = Key
    child_id: str
    text: str = Field(min_length=1, max_length=2000)
    success_criteria: str | None = Field(default=None, max_length=2000)
    date: date


class AssignmentPatch(TimesIn):
    command_id: str = Key
    version: int
    text: str = Field(min_length=1, max_length=2000)
    success_criteria: str | None = Field(default=None, max_length=2000)
    date: date


class CancelIn(BaseModel):
    command_id: str = Key
    version: int


class ReviewIn(BaseModel):
    idempotency_key: str = Key
    outcome: str = Field(pattern="^(done|partial|not_done)$")
    comment: str | None = Field(default=None, max_length=2000)
    # Для исправления: id текущей проверки, которую исправляем.
    supersedes_review_id: str | None = None


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class MarkIn(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class RecurrenceIn(TimesIn):
    idempotency_key: str = Key
    child_id: str
    text: str = Field(min_length=1, max_length=2000)
    success_criteria: str | None = Field(default=None, max_length=2000)
    weekdays: int = Field(ge=1, le=127)
    starts_on: date
    ends_on: date | None = None


class RecurrencePatch(BaseModel):
    command_id: str = Key
    version: int
    status: str = Field(pattern="^(active|paused|ended)$")


# ---------- общие проверки ----------


def own_assignment(db: Session, actor: Actor, aid: str) -> Assignment:
    a = db.get(Assignment, aid)
    if a is None or a.family_id != actor.family.id:
        raise not_found()
    if actor.child is not None and a.child_id != actor.child.id:
        raise not_found()
    return a


def own_child(db: Session, actor: Actor, child_id: str) -> Child:
    c = db.get(Child, child_id)
    if c is None or c.family_id != actor.family.id:
        raise not_found()
    return c


def replay(db: Session, actor: Actor, key: str, command: str) -> dict | None:
    done = db.get(ProcessedCommand, (key, actor.account.id))
    if done is None:
        return None
    if done.command != command:
        raise HTTPException(409, "Ключ команды уже использован для другой команды")
    return done.response


def remember(db: Session, actor: Actor, key: str, command: str, response: dict) -> dict:
    db.add(ProcessedCommand(idempotency_key=key, account_id=actor.account.id, command=command, response=response))
    return response


def _out(db: Session, actor: Actor, a: Assignment, detail: bool = True) -> dict:
    return assignment_out(db, a, actor.family.timezone, detail=detail, for_child=actor.child is not None)


# ---------- списки ----------


@router.get("/assignments/today")
def today(child_id: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)) -> list[dict]:
    """Активные с проверкой сегодня и раньше (просроченные) + закрытые с проверкой сегодня."""
    tz = actor.family.timezone
    start, end = timeutil.day_bounds_utc(timeutil.today(tz), tz)
    if actor.child is not None:
        child_id = actor.child.id
    q = select(Assignment).where(
        Assignment.family_id == actor.family.id,
        or_(
            (Assignment.state == "active") & (Assignment.check_at <= end),
            (Assignment.state == "closed") & Assignment.check_at.between(start, end),
        ),
    )
    if child_id:
        q = q.where(Assignment.child_id == child_id)
    return [_out(db, actor, a, detail=False) for a in db.scalars(q.order_by(Assignment.check_at)).all()]


@router.get("/history")
def history(
    child_id: str | None = None,
    period: str = Query("week", pattern="^(week|month|all)$"),
    outcome: str = Query("all", pattern="^(all|done|partial|not_done|cancelled)$"),
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
) -> dict:
    tz = actor.family.timezone
    if actor.child is not None:
        child_id = actor.child.id
    q = select(Assignment).where(
        Assignment.family_id == actor.family.id, Assignment.state.in_(("closed", "cancelled"))
    )
    since = history_window(tz, period)
    if since:
        q = q.where(Assignment.check_at >= since)
    if child_id:
        q = q.where(Assignment.child_id == child_id)
    items = [_out(db, actor, a, detail=False) for a in db.scalars(q.order_by(Assignment.check_at.desc())).all()]
    summary = {"done": 0, "partial": 0, "not_done": 0, "cancelled": 0, "marked_but_not_done": 0}
    for it in items:
        key = "cancelled" if it["state"] == "cancelled" else it["current_review"]["outcome"]
        summary[key] += 1
        if it["child_marked_at"] and key == "not_done":
            summary["marked_but_not_done"] += 1
    if outcome != "all":
        items = [
            it
            for it in items
            if (it["state"] == "cancelled") == (outcome == "cancelled")
            and (outcome == "cancelled" or it["current_review"]["outcome"] == outcome)
        ]
    return {"summary": summary, "items": items}


# ---------- задание ----------


@router.post("/assignments")
def create_assignment(body: AssignmentIn, actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    existing = db.scalar(select(Assignment).where(Assignment.idempotency_key == body.idempotency_key))
    if existing:
        if existing.family_id != actor.family.id:
            raise conflict("Ключ уже использован")
        return _out(db, actor, existing)
    child = own_child(db, actor, body.child_id)
    tz = actor.family.timezone
    a = Assignment(
        id=new_id(),
        family_id=actor.family.id,
        child_id=child.id,
        created_by_parent_id=actor.parent.id,
        text=body.text.strip(),
        success_criteria=(body.success_criteria or "").strip() or None,
        due_at=timeutil.to_utc(body.date, body.due_time, tz),
        check_at=timeutil.to_utc(body.date, body.check_time, tz),
        idempotency_key=body.idempotency_key,
    )
    db.add(a)
    db.flush()
    schedule_reminder(db, a)
    ev = audit(db, family_id=a.family_id, actor_account_id=actor.account.id, entity_type="assignment", entity_id=a.id, event_type="created", payload={"text": a.text})
    notify_change(db, ev=ev, type="assignment_changed", text=f"{actor.parent.name} дал(а) задание: {a.text} · {child.name}", assignment_id=a.id, exclude_parent_id=actor.parent.id)
    db.commit()
    return _out(db, actor, a)


@router.get("/assignments/{aid}")
def get_assignment(aid: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)) -> dict:
    return _out(db, actor, own_assignment(db, actor, aid))


@router.patch("/assignments/{aid}")
def update_assignment(aid: str, body: AssignmentPatch, actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    if (r := replay(db, actor, body.command_id, "assignment.update")) is not None:
        return r
    a = own_assignment(db, actor, aid)
    if a.state != "active":
        # TODO(open-question): AGENTS.md §31 п.1 — правка закрытого задания пока запрещена.
        raise HTTPException(409, "Менять можно только активное задание")
    if a.version != body.version:
        raise conflict()
    tz = actor.family.timezone
    old_check = a.check_at
    old = {"text": a.text, "check_at": a.check_at.isoformat(), "due_at": a.due_at.isoformat()}
    new_check = timeutil.to_utc(body.date, body.check_time, tz)
    check_changed = new_check != a.check_at
    a.text = body.text.strip()
    a.success_criteria = (body.success_criteria or "").strip() or None
    a.due_at = timeutil.to_utc(body.date, body.due_time, tz)
    a.check_at = new_check
    a.version += 1
    a.updated_at = utcnow()
    db.flush()
    if check_changed:
        schedule_reminder(db, a)
    ev = audit(db, family_id=a.family_id, actor_account_id=actor.account.id, entity_type="assignment", entity_id=a.id, event_type="changed", payload={"before": old})
    text = f"{actor.parent.name} изменил(а) задание: {a.text}"
    if check_changed:
        text += f" · проверка {timeutil.local(old_check, tz):%H:%M} → {timeutil.local(a.check_at, tz):%H:%M}"
    notify_change(db, ev=ev, type="assignment_changed", text=text, assignment_id=a.id, exclude_parent_id=actor.parent.id)
    out = remember(db, actor, body.command_id, "assignment.update", _out(db, actor, a))
    db.commit()
    return out


@router.post("/assignments/{aid}/cancel")
def cancel_assignment(aid: str, body: CancelIn, actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    if (r := replay(db, actor, body.command_id, "assignment.cancel")) is not None:
        return r
    a = own_assignment(db, actor, aid)
    if a.state != "active":
        raise HTTPException(409, "Отменить можно только активное задание")
    if a.version != body.version:
        raise conflict()
    a.state = "cancelled"
    a.cancelled_at = utcnow()
    a.cancelled_by_parent_id = actor.parent.id
    a.version += 1
    a.updated_at = utcnow()
    cancel_reminders(db, a.id)
    ev = audit(db, family_id=a.family_id, actor_account_id=actor.account.id, entity_type="assignment", entity_id=a.id, event_type="cancelled")
    notify_change(db, ev=ev, type="assignment_changed", text=f"{actor.parent.name} отменил(а): {a.text}", assignment_id=a.id, exclude_parent_id=actor.parent.id)
    out = remember(db, actor, body.command_id, "assignment.cancel", _out(db, actor, a))
    db.commit()
    return out


@router.post("/assignments/{aid}/reviews")
def review(aid: str, body: ReviewIn, actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    """Первая проверка закрывает задание; исправление — новая запись, старая остаётся (AGENTS.md §15)."""
    dup = db.scalar(select(AssignmentReview).where(AssignmentReview.idempotency_key == body.idempotency_key))
    if dup:
        a = own_assignment(db, actor, dup.assignment_id)
        return _out(db, actor, a)
    a = own_assignment(db, actor, aid)
    cur = current_review(db, a.id)
    if body.supersedes_review_id is None:
        if a.state != "active" or cur is not None:
            raise conflict("Задание уже проверено, обновите")
    else:
        if cur is None or cur.id != body.supersedes_review_id:
            raise conflict()
        cur.is_current = False
        db.flush()
    r = AssignmentReview(
        assignment_id=a.id,
        reviewer_parent_id=actor.parent.id,
        outcome=body.outcome,
        supersedes_review_id=body.supersedes_review_id,
        idempotency_key=body.idempotency_key,
    )
    db.add(r)
    if a.state == "active":
        a.state = "closed"
        a.closed_at = utcnow()
        cancel_reminders(db, a.id)
    a.version += 1
    a.updated_at = utcnow()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise conflict() from None
    if body.comment and body.comment.strip():
        disc = ensure_discussion(db, a.id)
        db.add(Comment(discussion_id=disc.id, author_parent_id=actor.parent.id, text=body.comment.strip()))
    corrected = body.supersedes_review_id is not None
    ev = audit(
        db,
        family_id=a.family_id,
        actor_account_id=actor.account.id,
        entity_type="review",
        entity_id=r.id,
        event_type="review_corrected" if corrected else "reviewed",
        payload={"assignment_id": a.id, "outcome": body.outcome},
    )
    verb = "исправил(а) результат" if corrected else "проверил(а)"
    notify_change(db, ev=ev, type="review_added", text=f"{actor.parent.name} {verb}: {a.text} — {OUTCOME_TEXT[body.outcome]}", assignment_id=a.id, exclude_parent_id=actor.parent.id)
    db.commit()
    return _out(db, actor, a)


@router.post("/assignments/{aid}/comments")
def add_comment(aid: str, body: CommentIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)) -> dict:
    a = own_assignment(db, actor, aid)
    disc = ensure_discussion(db, a.id)
    c = Comment(
        discussion_id=disc.id,
        author_parent_id=actor.parent.id if actor.parent else None,
        author_child_id=actor.child.id if actor.child else None,
        text=body.text.strip(),
    )
    db.add(c)
    db.flush()
    ev = audit(db, family_id=a.family_id, actor_account_id=actor.account.id, entity_type="comment", entity_id=c.id, event_type="created", payload={"assignment_id": a.id})
    who = actor.parent.name if actor.parent else actor.child.name
    notify_change(db, ev=ev, type="assignment_changed", text=f"{who} прокомментировал(а): {a.text}", assignment_id=a.id, exclude_parent_id=actor.parent.id if actor.parent else None)
    db.commit()
    return _out(db, actor, a)


@router.post("/assignments/{aid}/mark")
def child_mark(aid: str, body: MarkIn, actor: Actor = Depends(child_actor), db: Session = Depends(get_db)) -> dict:
    """Ребёнок отмечает «сделал». Не закрывает задание. Повтор — no-op."""
    a = own_assignment(db, actor, aid)
    if db.get(ChildMark, a.id):
        return _out(db, actor, a)
    if a.state != "active":
        raise HTTPException(409, "Задание уже закрыто или отменено")
    db.add(ChildMark(assignment_id=a.id, child_id=actor.child.id))
    if body.comment and body.comment.strip():
        disc = ensure_discussion(db, a.id)
        db.add(Comment(discussion_id=disc.id, author_child_id=actor.child.id, text=body.comment.strip()))
    db.flush()
    ev = audit(db, family_id=a.family_id, actor_account_id=actor.account.id, entity_type="assignment", entity_id=a.id, event_type="child_marked")
    notify_parents(db, family_id=a.family_id, type="child_marked", text=f"{actor.child.name} отметил(а) «сделал»: {a.text}", dedup_key=f"child_marked:{ev.id}", assignment_id=a.id)
    db.commit()
    return _out(db, actor, a)


# ---------- повторы ----------


@router.get("/recurrences")
def list_recurrences(child_id: str | None = None, actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> list[dict]:
    q = select(Recurrence).where(Recurrence.family_id == actor.family.id, Recurrence.status != "ended")
    if child_id:
        q = q.where(Recurrence.child_id == child_id)
    return [recurrence_out(r) for r in db.scalars(q.order_by(Recurrence.created_at)).all()]


@router.post("/recurrences")
def create_recurrence(body: RecurrenceIn, actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    existing = db.scalar(select(Recurrence).where(Recurrence.idempotency_key == body.idempotency_key))
    if existing:
        if existing.family_id != actor.family.id:
            raise conflict("Ключ уже использован")
        return recurrence_out(existing)
    if body.ends_on and body.ends_on < body.starts_on:
        raise HTTPException(422, "Дата окончания раньше начала")
    child = own_child(db, actor, body.child_id)
    r = Recurrence(
        family_id=actor.family.id,
        child_id=child.id,
        created_by_parent_id=actor.parent.id,
        text=body.text.strip(),
        success_criteria=(body.success_criteria or "").strip() or None,
        weekdays=body.weekdays,
        due_local_time=body.due_time,
        check_local_time=body.check_time,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        idempotency_key=body.idempotency_key,
    )
    db.add(r)
    db.flush()
    ev = audit(db, family_id=r.family_id, actor_account_id=actor.account.id, entity_type="recurrence", entity_id=r.id, event_type="created")
    tz = actor.family.timezone
    generate_for_recurrence(db, r, timeutil.today(tz), tz)
    notify_change(db, ev=ev, type="assignment_changed", text=f"{actor.parent.name} завёл(а) повтор: {r.text} · {child.name}", assignment_id=None, exclude_parent_id=actor.parent.id)
    db.commit()
    return recurrence_out(r)


@router.patch("/recurrences/{rid}")
def update_recurrence(rid: str, body: RecurrencePatch, actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    """Пауза, возобновление, завершение. Уже созданные задания не меняются (AGENTS.md §15)."""
    if (resp := replay(db, actor, body.command_id, "recurrence.update")) is not None:
        return resp
    r = db.get(Recurrence, rid)
    if r is None or r.family_id != actor.family.id:
        raise not_found()
    if r.version != body.version:
        raise conflict()
    if r.status == "ended":
        raise HTTPException(409, "Повтор уже завершён")
    before = r.status
    r.status = body.status
    r.version += 1
    r.updated_at = utcnow()
    audit(db, family_id=r.family_id, actor_account_id=actor.account.id, entity_type="recurrence", entity_id=r.id, event_type="changed", payload={"status": [before, r.status]})
    if r.status == "active":
        tz = actor.family.timezone
        generate_for_recurrence(db, r, timeutil.today(tz), tz)
    out = remember(db, actor, body.command_id, "recurrence.update", recurrence_out(r))
    db.commit()
    return out
