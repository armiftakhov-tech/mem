from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def make_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record) -> None:
        # Транзакциями управляем сами (BEGIN IMMEDIATE ниже), а не драйвер.
        dbapi_conn.isolation_level = None
        # AGENTS.md §7.3: WAL и foreign keys на каждом соединении.
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    @event.listens_for(engine, "begin")
    def _begin_immediate(conn) -> None:
        # Блокировка записи с начала транзакции: проверка прав и состояния и запись
        # идут в одном снимке (AGENTS.md §17), без SQLITE_BUSY при апгрейде чтения в запись.
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


@lru_cache
def _session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def session_for(engine: Engine) -> Session:
    return _session_factory(engine)()

