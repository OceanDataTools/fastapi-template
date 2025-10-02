FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y curl build-essential netcat-openbsd \
    && curl -sSL https://install.python-poetry.org | python3 - \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.local/bin:$PATH"

COPY ./app ./app


COPY pyproject.toml poetry.lock ./
COPY setup.sh entrypoint.sh ./
RUN chmod +x setup.sh entrypoint.sh

RUN ./setup.sh

RUN ls
RUN ls ./app

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
