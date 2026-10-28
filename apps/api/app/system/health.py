from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text

from app.db import get_engine

router = APIRouter(prefix="/health", tags=["system"])

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def head_revision() -> str | None:
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()


@router.get("/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/ready")
def ready(engine: Engine = Depends(get_engine)) -> JSONResponse:
    # AGENTS.md §22: ready только после применения миграций.
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            current = MigrationContext.configure(conn).get_current_revision()
    except Exception as exc:
        return JSONResponse({"status": "not_ready", "reason": type(exc).__name__}, status_code=503)

    head = head_revision()
    if current != head:
        return JSONResponse(
            {"status": "not_ready", "reason": "migrations_pending", "current": current, "head": head},
            status_code=503,
        )
    return JSONResponse({"status": "ok", "revision": current})
