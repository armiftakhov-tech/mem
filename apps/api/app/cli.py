"""Админские команды. Запуск: docker compose exec app python -m app.cli <команда>."""

import argparse
import secrets
import sys

from sqlalchemy import select, update

from app.db import get_engine, session_for
from app.models import Account, utcnow
from app.models import Session as DbSession
from app.routers.auth import issue_bootstrap_token, norm_login, setup_required
from app.security import hash_password
from app.services import audit


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bootstrap-token", help="выдать токен первой настройки")
    rp = sub.add_parser("reset-password", help="сбросить пароль аккаунта")
    rp.add_argument("login")
    args = p.parse_args()

    with session_for(get_engine()) as db:
        if args.cmd == "bootstrap-token":
            if not setup_required(db):
                print("Семья уже создана, токен не нужен.", file=sys.stderr)
                return 1
            print(issue_bootstrap_token(db))
            return 0

        acc = db.scalar(select(Account).where(Account.login == norm_login(args.login)))
        if acc is None:
            print("Аккаунт не найден.", file=sys.stderr)
            return 1
        password = secrets.token_urlsafe(9)
        acc.password_hash = hash_password(password)
        db.execute(update(DbSession).where(DbSession.account_id == acc.id).values(revoked_at=utcnow()))
        audit(db, family_id=None, actor_account_id=None, entity_type="account", entity_id=acc.id, event_type="password_reset")
        db.commit()
        print(f"Новый пароль для {acc.login}: {password}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
