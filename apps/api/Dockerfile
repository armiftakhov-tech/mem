FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/api

COPY pyproject.toml ./
COPY app ./app
RUN pip install .

COPY alembic.ini entrypoint.sh ./
COPY migrations ./migrations

RUN useradd --uid 10001 --no-create-home app \
    && mkdir /data && chown app:app /data
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)"
ENTRYPOINT ["./entrypoint.sh"]
