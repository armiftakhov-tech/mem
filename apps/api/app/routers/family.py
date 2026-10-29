"""Семья, дети, родители, приглашения, уведомления и настройки."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import timeutil
from app.config import get_settings
from app.deps import Actor, current_actor, get_db, not_found, parent_actor
from app.models import (
    Account,
    Assignment,
    Child,
    FamilyInvitation,
    Notification,
    Parent,
    ParentChildRelation,
    Recurrence,
    utcnow,
)
from app.models import Session as DbSession
from app.routers.auth import check_relation, norm_login
from app.security import hash_password, new_code, sha256
from app.services import _settings, audit

router = APIRouter(tags=["family"])


class ChildIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    birth_date: date | None = None
    relation_type: str = "other"


class ChildAccountIn(BaseModel):
    login: str = Field(min_length=2, max_length=60)
    password: str = Field(min_length=6, max_length=200)


class SettingsIn(BaseModel):
    reminders_enabled: bool
    changes_enabled: bool
    browser_notifications_enabled: bool


def own_child(db: Session, actor: Actor, child_id: str) -> Child:
    c = db.get(Child, child_id)
    if c is None or c.family_id != actor.family.id:
        raise not_found()
    return c


def child_out(db: Session, c: Child, tz: str) -> dict:
    start, end = timeutil.day_bounds_utc(timeutil.today(tz), tz)
    now = utcnow()
    today_q = select(func.count()).select_from(Assignment).where(
        Assignment.child_id == c.id, Assignment.state != "cancelled", Assignment.check_at.between(start, end)
    )
    to_check = db.scalar(
        select(func.count()).select_from(Assignment).where(
            Assignment.child_id == c.id, Assignment.state == "active", Assignment.due_at <= now
        )
    )
    has_history = bool(
        db.scalar(select(Assignment.id).where(Assignment.child_id == c.id).limit(1))
        or db.scalar(select(Recurrence.id).where(Recurrence.child_id == c.id).limit(1))
    )
    login = db.get(Account, c.account_id).login if c.account_id else None
    age = None
    if c.birth_date:
        t = date.today()
        age = t.year - c.birth_date.year - ((t.month, t.day) < (c.birth_date.month, c.birth_date.day))
    return {
        "id": c.id,
        "name": c.name,
        "birth_date": c.birth_date.isoformat() if c.birth_date else None,
        "age": age,
        "today_count": db.scalar(today_q),
        "to_check_count": to_check,
        "can_delete": not has_history,
        "login": login,
    }


@router.get("/me")
def me(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)) -> dict:
    tz = actor.family.timezone
    out = {
        "kind": actor.account.kind,
        "login": actor.account.login,
        "family": {"id": actor.family.id, "timezone": tz},
        "today": timeutil.today(tz).isoformat(),
    }
    if actor.is_parent:
        out["parent"] = {"id": actor.parent.id, "name": actor.parent.name}
        out["children"] = [
            {"id": c.id, "name": c.name}
            for c in db.scalars(select(Child).where(Child.family_id == actor.family.id).order_by(Child.created_at))
        ]
    else:
        out["child"] = {"id": actor.child.id, "name": actor.child.name}
    return out


@router.get("/children")
def list_children(actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> list[dict]:
    kids = db.scalars(select(Child).where(Child.family_id == actor.family.id).order_by(Child.created_at)).all()
    return [child_out(db, c, actor.family.timezone) for c in kids]


@router.post("/children")
def create_child(body: ChildIn, actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    c = Child(family_id=actor.family.id, name=body.name.strip(), birth_date=body.birth_date)
    db.add(c)
    db.flush()
    rel = check_relation(body.relation_type)
    # Инвариант: каждый активный родитель связан со всеми детьми семьи.
    for p in db.scalars(select(Parent).where(Parent.family_id == actor.family.id, Parent.status == "active")):
        db.add(ParentChildRelation(parent_id=p.id, child_id=c.id, relation_type=rel if p.id == actor.parent.id else "other"))
    audit(db, family_id=actor.family.id, actor_account_id=actor.account.id, entity_type="child", entity_id=c.id, event_type="created")
    db.commit()
    return child_out(db, c, actor.family.timezone)


@router.patch("/children/{child_id}")
def update_child(child_id: str, body: ChildIn, actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    c = own_child(db, actor, child_id)
    c.name, c.birth_date = body.name.strip(), body.birth_date
    rel = db.scalar(
        select(ParentChildRelation).where(
            ParentChildRelation.parent_id == actor.parent.id, ParentChildRelation.child_id == c.id
        )
    )
    if rel:
        rel.relation_type = check_relation(body.relation_type)
    audit(db, family_id=actor.family.id, actor_account_id=actor.account.id, entity_type="child", entity_id=c.id, event_type="changed")
    db.commit()
    return child_out(db, c, actor.family.timezone)


@router.delete("/children/{child_id}")
def delete_child(child_id: str, actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    c = own_child(db, actor, child_id)
    if db.scalar(select(Assignment.id).where(Assignment.child_id == c.id).limit(1)) or db.scalar(
        select(Recurrence.id).where(Recurrence.child_id == c.id).limit(1)
    ):
        raise HTTPException(409, "У ребёнка есть задания или повторы — удалить нельзя")
    account_id = c.account_id
    audit(db, family_id=actor.family.id, actor_account_id=actor.account.id, entity_type="child", entity_id=c.id, event_type="deleted", payload={"name": c.name})
    db.delete(c)
    db.flush()
    if account_id:
        acc = db.get(Account, account_id)
        acc.status = "blocked"
        db.execute(update(DbSession).where(DbSession.account_id == account_id).values(revoked_at=utcnow()))
    db.commit()
    return {"ok": True}


@router.put("/children/{child_id}/account")
def set_child_account(
    child_id: str, body: ChildAccountIn, actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)
) -> dict:
    """Создать вход ребёнку или сменить ему логин и пароль. Старые сессии ребёнка отзываются."""
    c = own_child(db, actor, child_id)
    login = norm_login(body.login)
    clash = db.scalar(select(Account).where(Account.login == login))
    if clash and clash.id != c.account_id:
        raise HTTPException(409, "Такой логин уже занят")
    if c.account_id:
        acc = db.get(Account, c.account_id)
        acc.login, acc.password_hash = login, hash_password(body.password)
        db.execute(update(DbSession).where(DbSession.account_id == acc.id).values(revoked_at=utcnow()))
        event = "child_login_changed"
    else:
        acc = Account(login=login, kind="child", password_hash=hash_password(body.password))
        db.add(acc)
        db.flush()
        c.account_id = acc.id
        event = "child_login_created"
    audit(db, family_id=actor.family.id, actor_account_id=actor.account.id, entity_type="child", entity_id=c.id, event_type=event)
    db.commit()
    return child_out(db, c, actor.family.timezone)


@router.get("/parents")
def list_parents(actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> list[dict]:
    ps = db.scalars(
        select(Parent).where(Parent.family_id == actor.family.id, Parent.status == "active").order_by(Parent.created_at)
    ).all()
    return [{"id": p.id, "name": p.name, "is_me": p.id == actor.parent.id} for p in ps]


# ---------- приглашения ----------


def invitation_out(db: Session, inv: FamilyInvitation) -> dict:
    now = utcnow()
    status = "pending"
    if inv.accepted_at:
        status = "accepted"
    elif inv.revoked_at:
        status = "revoked"
    elif inv.expires_at <= now:
        status = "expired"
    return {
        "id": inv.id,
        "hint": f"{inv.code_hint}-••••",
        "created_by_name": db.get(Parent, inv.created_by_parent_id).name,
        "expires_at": inv.expires_at.isoformat(),
        "status": status,
    }


@router.get("/invitations")
def list_invitations(actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> list[dict]:
    invs = db.scalars(
        select(FamilyInvitation)
        .where(FamilyInvitation.family_id == actor.family.id)
        .order_by(FamilyInvitation.created_at.desc())
        .limit(20)
    ).all()
    return [invitation_out(db, i) for i in invs]


@router.post("/invitations")
def create_invitation(actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    code = new_code()
    inv = FamilyInvitation(
        family_id=actor.family.id,
        code_hash=sha256(code),
        code_hint=code[:4],
        created_by_parent_id=actor.parent.id,
        expires_at=utcnow() + timedelta(hours=get_settings().invitation_hours),
    )
    db.add(inv)
    db.flush()
    audit(db, family_id=actor.family.id, actor_account_id=actor.account.id, entity_type="invitation", entity_id=inv.id, event_type="created")
    db.commit()
    # Полный код отдаётся один раз и нигде не хранится.
    return {**invitation_out(db, inv), "code": code}


@router.post("/invitations/{inv_id}/revoke")
def revoke_invitation(inv_id: str, actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    inv = db.get(FamilyInvitation, inv_id)
    if inv is None or inv.family_id != actor.family.id:
        raise not_found()
    if inv.accepted_at is None and inv.revoked_at is None:
        inv.revoked_at = utcnow()
        audit(db, family_id=actor.family.id, actor_account_id=actor.account.id, entity_type="invitation", entity_id=inv.id, event_type="revoked")
        db.commit()
    return invitation_out(db, inv)


# ---------- уведомления ----------


@router.get("/notifications")
def list_notifications(actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    items = db.scalars(
        select(Notification)
        .where(Notification.parent_id == actor.parent.id)
        .order_by(Notification.created_at.desc())
        .limit(100)
    ).all()
    return {
        "unread": sum(1 for n in items if n.read_at is None),
        "items": [
            {
                "id": n.id,
                "type": n.type,
                "text": n.text,
                "assignment_id": n.assignment_id,
                "created_at": n.created_at.isoformat(),
                "read": n.read_at is not None,
            }
            for n in items
        ],
    }


@router.get("/notifications/unread")
def unread_count(actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    n = db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.parent_id == actor.parent.id, Notification.read_at.is_(None)
        )
    )
    return {"unread": n}


@router.post("/notifications/read-all")
def read_all(actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    db.execute(
        update(Notification)
        .where(Notification.parent_id == actor.parent.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    db.commit()
    return {"ok": True}


@router.post("/notifications/{nid}/read")
def read_one(nid: str, actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    n = db.get(Notification, nid)
    if n is None or n.parent_id != actor.parent.id:
        raise not_found()
    if n.read_at is None:
        n.read_at = utcnow()
        db.commit()
    return {"ok": True}


@router.get("/settings/notifications")
def get_settings_(actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    s = _settings(db, actor.parent.id)
    db.commit()
    return {
        "reminders_enabled": s.reminders_enabled,
        "changes_enabled": s.changes_enabled,
        "browser_notifications_enabled": s.browser_notifications_enabled,
    }


@router.put("/settings/notifications")
def put_settings(body: SettingsIn, actor: Actor = Depends(parent_actor), db: Session = Depends(get_db)) -> dict:
    s = _settings(db, actor.parent.id)
    s.reminders_enabled = body.reminders_enabled
    s.changes_enabled = body.changes_enabled
    s.browser_notifications_enabled = body.browser_notifications_enabled
    s.updated_at = utcnow()
    db.commit()
    return body.model_dump()


