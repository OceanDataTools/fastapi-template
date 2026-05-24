FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -sSL https://install.python-poetry.org | python3 - \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.local/bin:$PATH"
# Install packages into system Python so the venv is not stored under /app,
# which would be shadowed by the docker-compose volume mount at runtime.
ENV POETRY_VIRTUALENVS_CREATE=false

# Copy dependency files first so this layer is cached independently of
# application code changes.
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root

COPY ./app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
