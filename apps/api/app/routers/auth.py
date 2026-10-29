"""Вход, первичная настройка, приглашение второго родителя (AGENTS.md §10–12)."""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import SESSION_COOKIE, Actor, client_ip, current_actor, get_db
from app.models import (
    RELATION_TYPES,
    Account,
    BootstrapToken,
    Child,
    Family,
    FamilyInvitation,
    LoginAttempt,
    Parent,
    ParentChildRelation,
    utcnow,
)
from app.models import Session as DbSession
from app.security import DUMMY_HASH, hash_password, new_token, normalize_code, sha256, verify_password
from app.services import audit
from app.timeutil import valid_timezone

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

CSRF_COOKIE = "discipline_csrf"


class ChildIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    birth_date: date | None = None


class SetupIn(BaseModel):
    token: str
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    timezone: str
    relation_type: str = "other"
    child: ChildIn


class LoginIn(BaseModel):
    login: str
    password: str


class PasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=200)


class AcceptIn(BaseModel):
    code: str
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=200)
    name: str | None = Field(default=None, max_length=100)
    relation_type: str = "other"


def norm_login(login: str) -> str:
    return login.strip().lower()


def start_session(db: Session, response: Response, account: Account) -> None:
    s = get_settings()
    raw, csrf = new_token(), new_token()
    db.add(
        DbSession(
            id_hash=sha256(raw),
            account_id=account.id,
            csrf_token_hash=sha256(csrf),
            expires_at=utcnow() + timedelta(days=s.session_days),
        )
    )
    account.last_login_at = utcnow()
    max_age = s.session_days * 86400
    response.set_cookie(
        SESSION_COOKIE, raw, max_age=max_age, httponly=True, secure=s.cookie_secure, samesite="strict"
    )
    # Double-submit: JS читает этот cookie и шлёт его в заголовке X-CSRF-Token.
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=s.cookie_secure, samesite="strict")


def check_relation(value: str) -> str:
    if value not in RELATION_TYPES:
        raise HTTPException(422, "Неизвестный тип связи")
    return value


def issue_bootstrap_token(db: Session) -> str:
    token = new_token()[:24]
    hours = get_settings().bootstrap_token_hours
    db.add(BootstrapToken(token_hash=sha256(token), expires_at=utcnow() + timedelta(hours=hours)))
    db.commit()
    return token


def setup_required(db: Session) -> bool:
    return db.scalar(select(func.count()).select_from(Family)) == 0


@router.get("/state")
def state(db: Session = Depends(get_db)) -> dict:
    return {"setup_required": setup_required(db)}


@router.post("/setup")
def setup(body: SetupIn, response: Response, db: Session = Depends(get_db)) -> dict:
    if not setup_required(db):
        raise HTTPException(409, "Семья уже создана. Открытой регистрации нет")
    tok = db.get(BootstrapToken, sha256(body.token.strip()))
    if tok is None or tok.used_at is not None or tok.expires_at <= utcnow():
        raise HTTPException(400, "Bootstrap-токен неверный или истёк")
    if not valid_timezone(body.timezone):
        raise HTTPException(422, "Неизвестный часовой пояс")
    login = norm_login(body.email)
    if db.scalar(select(Account.id).where(Account.login == login)):
        raise HTTPException(409, "Такой логин уже есть")

    tok.used_at = utcnow()
    account = Account(login=login, kind="parent", password_hash=hash_password(body.password))
    family = Family(timezone=body.timezone)
    db.add_all([account, family])
    db.flush()
    parent = Parent(family_id=family.id, account_id=account.id, name=body.name.strip())
    child = Child(family_id=family.id, name=body.child.name.strip(), birth_date=body.child.birth_date)
    db.add_all([parent, child])
    db.flush()
    db.add(ParentChildRelation(parent_id=parent.id, child_id=child.id, relation_type=check_relation(body.relation_type)))
    audit(db, family_id=family.id, actor_account_id=account.id, entity_type="family", entity_id=family.id, event_type="created")
    start_session(db, response, account)
    db.commit()
    log.info("family created")
    return {"ok": True}


def _too_many_failures(db: Session, login: str, ip: str | None) -> bool:
    s = get_settings()
    since = utcnow() - timedelta(minutes=s.login_window_minutes)
    base = select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.success.is_(False), LoginAttempt.attempted_at >= since
    )
    by_login = db.scalar(base.where(LoginAttempt.login_normalized == login))
    by_ip = db.scalar(base.where(LoginAttempt.ip == ip)) if ip else 0
    # IP общий для всей домашней сети, поэтому лимит по нему мягче.
    return by_login >= s.login_max_failures or by_ip >= s.login_max_failures * 4


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    login = norm_login(body.login)
    ip = client_ip(request)
    if _too_many_failures(db, login, ip):
        raise HTTPException(429, "Слишком много попыток, подождите")
    account = db.scalar(select(Account).where(Account.login == login))
    ok = verify_password(account.password_hash if account else DUMMY_HASH, body.password)
    ok = ok and account is not None and account.status == "active"
    db.add(LoginAttempt(login_normalized=login, account_id=account.id if account else None, ip=ip, success=ok))
    family_id = None
    if account:
        owner = db.scalar(select(Parent.family_id).where(Parent.account_id == account.id)) or db.scalar(
            select(Child.family_id).where(Child.account_id == account.id)
        )
        family_id = owner
    audit(
        db,
        family_id=family_id,
        actor_account_id=account.id if account else None,
        entity_type="account",
        entity_id=account.id if account else None,
        event_type="login_ok" if ok else "login_failed",
    )
    if not ok:
        db.commit()
        log.info("login failed")
        raise HTTPException(401, "Неверный логин или пароль")
    start_session(db, response, account)
    db.commit()
    log.info("login ok")
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        sess = db.get(DbSession, sha256(raw))
        if sess and sess.revoked_at is None:
            sess.revoked_at = utcnow()
            db.commit()
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)
    return {"ok": True}


@router.post("/password")
def change_password(body: PasswordIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)) -> dict:
    account = db.get(Account, actor.account.id)
    if not verify_password(account.password_hash, body.old_password):
        raise HTTPException(400, "Старый пароль неверный")
    account.password_hash = hash_password(body.new_password)
    audit(db, family_id=actor.family.id, actor_account_id=account.id, entity_type="account", entity_id=account.id, event_type="password_changed")
    db.commit()
    return {"ok": True}


@router.post("/accept-invitation")
def accept_invitation(body: AcceptIn, response: Response, db: Session = Depends(get_db)) -> dict:
    """Новый аккаунт или существующий без семьи. Повтор тем же аккаунтом — no-op (AGENTS.md §12)."""
    inv = db.scalar(select(FamilyInvitation).where(FamilyInvitation.code_hash == sha256(normalize_code(body.code))))
    login = norm_login(body.email)
    account = db.scalar(select(Account).where(Account.login == login))

    if inv and inv.accepted_by_account_id and account and inv.accepted_by_account_id == account.id:
        if not verify_password(account.password_hash, body.password):
            raise HTTPException(401, "Неверный логин или пароль")
        start_session(db, response, account)
        db.commit()
        return {"ok": True}

    if inv is None or inv.revoked_at or inv.accepted_at or inv.expires_at <= utcnow():
        raise HTTPException(400, "Код недействителен или истёк")

    if account:
        if account.kind != "parent" or not verify_password(account.password_hash, body.password):
            raise HTTPException(401, "Неверный логин или пароль")
        if db.scalar(select(Parent.id).where(Parent.account_id == account.id)):
            raise HTTPException(409, "Этот аккаунт уже состоит в семье")
    else:
        if not body.name:
            raise HTTPException(422, "Укажите имя")
        account = Account(login=login, kind="parent", password_hash=hash_password(body.password))
        db.add(account)
        db.flush()

    parent = Parent(family_id=inv.family_id, account_id=account.id, name=(body.name or login).strip())
    db.add(parent)
    db.flush()
    rel = check_relation(body.relation_type)
    for child in db.scalars(select(Child).where(Child.family_id == inv.family_id)).all():
        db.add(ParentChildRelation(parent_id=parent.id, child_id=child.id, relation_type=rel))
    inv.accepted_by_account_id = account.id
    inv.accepted_at = utcnow()
    audit(db, family_id=inv.family_id, actor_account_id=account.id, entity_type="invitation", entity_id=inv.id, event_type="accepted")
    start_session(db, response, account)
    db.commit()
    return {"ok": True}
