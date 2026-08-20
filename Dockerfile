FROM python:3.14-slim

ENV POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

WORKDIR /app

RUN pip install poetry

COPY pyproject.toml poetry.lock* /app/
RUN poetry install --no-ansi --without dev --no-root

COPY . /app/
RUN chmod +x /app/entrypoint.sh

RUN poetry config installer.max-workers 10
RUN poetry install --no-ansi --without dev

EXPOSE 8000