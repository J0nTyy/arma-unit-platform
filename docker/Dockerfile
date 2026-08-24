FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/app

COPY pyproject.toml README.md alembic.ini ./
COPY app ./app
COPY migrations ./migrations
COPY content ./content

RUN pip install .

# Migrations are applied by the compose command before start; the default
# command just runs the application.
CMD ["python", "-m", "app.main"]
