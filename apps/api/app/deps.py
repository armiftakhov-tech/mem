from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db import get_engine, session_for
from app.models import Account, Child, Family, Parent
from app.models import Session as DbSession
from app.models import utcnow
from app.security import sha256

SESSION_COOKIE = "discipline_session"
CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_db(engine: Engine = Depends(get_engine)) -> Iterator[Session]:
    db = session_for(engine)
    try:
        yield db
    finally:
        db.close()


def not_found() -> HTTPException:
    # Объект чужой семьи отдаётся как 404, а не 403 (docs/02 §20).
    return HTTPException(404, "Не найдено")


def conflict(message: str = "Уже изменено, обновите") -> HTTPException:
    return HTTPException(409, message)


@dataclass
class Actor:
    account: Account
    family: Family
    parent: Parent | None = None
    child: Child | None = None

    @property
    def is_parent(self) -> bool:
        return self.parent is not None


def current_actor(request: Request, db: Session = Depends(get_db)) -> Actor:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise HTTPException(401, "Нужно войти")
    now = utcnow()
    sess = db.get(DbSession, sha256(raw))
    if sess is None or sess.revoked_at is not None or sess.expires_at <= now:
        raise HTTPException(401, "Нужно войти")
    if request.method in UNSAFE_METHODS:
        token = request.headers.get(CSRF_HEADER, "")
        if sha256(token) != sess.csrf_token_hash:
            raise HTTPException(403, "CSRF-проверка не пройдена, обновите страницу")

    # AGENTS.md §10: активность аккаунта и принадлежность к семье — на каждом запросе.
    account = db.get(Account, sess.account_id)
    if account is None or account.status != "active":
        raise HTTPException(401, "Нужно войти")
    if account.kind == "parent":
        parent = db.scalar(select(Parent).where(Parent.account_id == account.id))
        if parent is None or parent.status != "active":
            raise HTTPException(401, "Нужно войти")
        actor = Actor(account=account, family=db.get(Family, parent.family_id), parent=parent)
    else:
        child = db.scalar(select(Child).where(Child.account_id == account.id))
        if child is None:
            raise HTTPException(401, "Нужно войти")
        actor = Actor(account=account, family=db.get(Family, child.family_id), child=child)

    if now - sess.last_seen_at > timedelta(minutes=5):
        sess.last_seen_at = now
        db.commit()
    return actor


def parent_actor(actor: Actor = Depends(current_actor)) -> Actor:
    if not actor.is_parent:
        raise HTTPException(403, "Доступно только родителям")
    return actor


def child_actor(actor: Actor = Depends(current_actor)) -> Actor:
    if actor.child is None:
        raise HTTPException(403, "Доступно только ребёнку")
    return actor


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
