"""Durable-планировщик: состояние в БД, поток только будит обработку (AGENTS.md §18)."""

import logging
import threading

from sqlalchemy import Engine

from app.db import session_for
from app.services import generate_today, process_due_reminders

log = logging.getLogger(__name__)


def tick(engine: Engine) -> None:
    with session_for(engine) as db:
        generate_today(db)
        process_due_reminders(db)
        db.commit()


class Scheduler:
    def __init__(self, engine: Engine, interval: int) -> None:
        self.engine, self.interval = engine, interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="scheduler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        # Первый проход сразу после старта: догоняем пропущенное во время простоя.
        while not self._stop.is_set():
            try:
                tick(self.engine)
            except Exception:
                log.exception("scheduler tick failed")
            self._stop.wait(self.interval)
