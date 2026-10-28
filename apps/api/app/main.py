import logging

from fastapi import FastAPI

from app.config import get_settings
from app.system import health

logging.basicConfig(level=get_settings().log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# Readiness-проверка каждые 15 с не должна засорять лог строками alembic.
logging.getLogger("alembic").setLevel(logging.WARNING)

app = FastAPI(title="Дисциплина", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(health.router)
