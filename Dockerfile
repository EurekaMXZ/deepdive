FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md .python-version ./
RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev

COPY backend ./backend
COPY docs ./docs
COPY prompts ./prompts
COPY profiles ./profiles

ENV PATH="/app/.venv/bin:${PATH}"

CMD ["python", "-m", "backend.api.runtime"]
