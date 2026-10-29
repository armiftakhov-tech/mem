import os
import uuid

os.environ.setdefault("DISCIPLINE_SCHEDULER_ENABLED", "false")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import get_engine, make_engine, session_for  # noqa: E402
from app.main import app  # noqa: E402
from app.routers.auth import issue_bootstrap_token  # noqa: E402
from app.system.health import ALEMBIC_INI  # noqa: E402


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
    yield TestClient(app, base_url="https://testserver")
    app.dependency_overrides.clear()


def key() -> str:
    return uuid.uuid4().hex


class Api:
    """Отдельный браузер: свои cookie и CSRF-заголовок."""

    def __init__(self, engine):
        self.c = TestClient(app, base_url="https://testserver")
        self.engine = engine

    def _headers(self):
        token = self.c.cookies.get("discipline_csrf")
        return {"X-CSRF-Token": token} if token else {}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers=self._headers(), **kw)

    def patch(self, url, json=None):
        return self.c.patch(url, json=json, headers=self._headers())

    def put(self, url, json=None):
        return self.c.put(url, json=json, headers=self._headers())

    def delete(self, url):
        return self.c.delete(url, headers=self._headers())


@pytest.fixture
def make_api(engine, migrate):
    migrate()
    app.dependency_overrides[get_engine] = lambda: engine
    yield lambda: Api(engine)
    app.dependency_overrides.clear()


def setup_family(api: Api, email="papa@home", name="Артем", child="Маша", tz="Europe/Moscow"):
    with session_for(api.engine) as db:
        token = issue_bootstrap_token(db)
    r = api.post(
        "/auth/setup",
        json={
            "token": token,
            "email": email,
            "password": "password1",
            "name": name,
            "timezone": tz,
            "relation_type": "father",
            "child": {"name": child},
        },
    )
    assert r.status_code == 200, r.text
    return api.get("/me").json()


@pytest.fixture
def papa(make_api):
    api = make_api()
    api.me = setup_family(api)
    api.child_id = api.me["children"][0]["id"]
    return api


@pytest.fixture
def mama(papa, make_api):
    code = papa.post("/invitations").json()["code"]
    api = make_api()
    r = api.post(
        "/auth/accept-invitation",
        json={"code": code, "email": "mama@home", "password": "password2", "name": "Лена", "relation_type": "mother"},
    )
    assert r.status_code == 200, r.text
    api.me = api.get("/me").json()
    return api
