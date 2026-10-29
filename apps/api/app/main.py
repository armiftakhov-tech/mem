import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db import get_engine, session_for
from app.routers import assignments, auth, family
from app.scheduler import Scheduler
from app.system import health

logging.basicConfig(level=get_settings().log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# Readiness-проверка каждые 15 с не должна засорять лог строками alembic.
logging.getLogger("alembic").setLevel(logging.WARNING)
log = logging.getLogger("app")


def announce_bootstrap_token() -> None:
    """Пока семьи нет, выдаём одноразовый токен в лог контейнера — это консоль администратора."""
    with session_for(get_engine()) as db:
        if auth.setup_required(db):
            token = auth.issue_bootstrap_token(db)
            hours = get_settings().bootstrap_token_hours
            log.warning("BOOTSTRAP TOKEN: %s (одноразовый, действует %d ч)", token, hours)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    log.info("app starting")
    announce_bootstrap_token()
    scheduler = None
    if settings.scheduler_enabled:
        scheduler = Scheduler(get_engine(), settings.scheduler_interval_seconds)
        scheduler.start()
    yield
    if scheduler:
        scheduler.stop()
    log.info("app stopped")


app = FastAPI(title="Дисциплина", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(family.router)
app.include_router(assignments.router)
