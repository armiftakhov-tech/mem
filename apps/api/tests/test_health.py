from sqlalchemy import text


def test_live(client):
    assert client.get("/health/live").json() == {"status": "ok"}


def test_ready_fails_before_migrations(client):
    r = client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["reason"] == "migrations_pending"


def test_ready_after_migrations(client, migrate):
    migrate()
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "revision": "0001"}


def test_sqlite_pragmas(engine):
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
