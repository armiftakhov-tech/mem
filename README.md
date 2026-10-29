# Дисциплина

Приложение для родителей: дать задание ребёнку, проверить в назначенное время, сохранить результат. Требования — [`AGENTS.md`](AGENTS.md), модель данных — [`docs/02-domain-model.md`](docs/02-domain-model.md).

Сейчас готов этап 0: каркас. Экранов ещё нет, только проверка, что связка Caddy → API → SQLite жива.

## Запуск на ноутбуке

Нужен Docker Desktop (macOS, Windows) или Docker Engine с Compose (Linux).

```sh
git clone https://github.com/armiftakhov-tech/mem.git
cd mem
docker compose -f deploy/compose/compose.yaml up -d --build
```

Открыть https://localhost:8443. Должно быть «Сервер готов, схема БД 0001».

Браузер сначала ругнётся на сертификат: Caddy выпускает его своим локальным CA. Чтобы предупреждения не было, достать корневой сертификат и добавить в доверенные:

```sh
docker compose -f deploy/compose/compose.yaml cp caddy:/data/caddy/pki/authorities/local/root.crt ./root.crt
```

- macOS: открыть `root.crt` в «Связке ключей», в свойствах выставить «Всегда доверять».
- Windows: двойной клик → «Установить сертификат» → «Доверенные корневые центры сертификации».
- Linux: `sudo cp root.crt /usr/local/share/ca-certificates/discipline.crt && sudo update-ca-certificates`, Firefox — отдельно в настройках.

Остановить: `docker compose -f deploy/compose/compose.yaml down`. Данные лежат в Docker volume `discipline_app-data` и переживают остановку. Удалить вместе с данными: `down -v`.

Порт и имя меняются через `deploy/compose/.env`, образец — [`.env.example`](.env.example).

## Проверка

- `https://localhost:8443/api/health/live` — процесс жив.
- `https://localhost:8443/api/health/ready` — миграции применены, БД доступна.

## Разработка без Docker

```sh
cd apps/api && python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
pytest
DISCIPLINE_DATABASE_PATH=./dev.db alembic upgrade head
DISCIPLINE_DATABASE_PATH=./dev.db uvicorn app.main:app --reload
```

```sh
cd apps/web && npm ci && npm run dev
```

## Структура

- `apps/api/` — FastAPI, SQLAlchemy 2, Alembic, SQLite (WAL, foreign keys).
- `apps/web/` — React + Vite, PWA-манифест.
- `deploy/compose/` — Docker Compose: `app` и `caddy`. Наружу открыт только HTTPS Caddy, по умолчанию на `127.0.0.1`.
- `deploy/caddy/` — Caddyfile и сборка образа с фронтендом.
- `docs/` — модель данных и [подготовка Raspberry Pi](docs/raspberry-setup.md).
- `.github/workflows/ci.yml` — тесты и сборка образов под `linux/arm64` с запуском стека.

## На Raspberry Pi

Те же команды. В `deploy/compose/.env` поставить `SITE_ADDRESS=discipline.home.arpa`, `HTTPS_BIND` — адрес Pi в домашней сети, `HTTPS_PORT=443`. WireGuard, firewall и бэкапы — этап 5.
