FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/api

COPY pyproject.toml ./
COPY app ./app
RUN pip install .

COPY alembic.ini entrypoint.sh ./
# Клон на Windows может принести CRLF: без этого /bin/sh не запустит скрипт.
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh
COPY migrations ./migrations

RUN useradd --uid 10001 --no-create-home app \
    && mkdir /data && chown app:app /data
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=10s --start-period=60s --start-interval=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=8)"
ENTRYPOINT ["./entrypoint.sh"]
