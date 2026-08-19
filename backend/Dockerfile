FROM python:3.12.13-slim

WORKDIR /app

RUN pip install --no-cache-dir uv==0.11.32

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY tests/fixtures ./tests/fixtures
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "serviceflow.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
