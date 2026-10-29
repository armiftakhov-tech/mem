import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.db import get_engine, make_engine
from app.main import app
from app.system.health import ALEMBIC_INI


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def engine(db_url):
    eng = make_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def migrate(db_url):
    def _run(revision: str = "head") -> None:
        cfg = Config(str(ALEMBIC_INI))
        cfg.attributes["database_url"] = db_url
        command.upgrade(cfg, revision)

    return _run


@pytest.fixture
def client(engine):
    app.dependency_overrides[get_engine] = lambda: engine
    yield TestClient(app)
    app.dependency_overrides.clear()
