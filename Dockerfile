# A small local teaching deployment; never publishes credentials or source PDFs.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Install only runtime dependencies. The source code is installed as a package.
COPY pyproject.toml requirements-answer.txt requirements-app.txt ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir . \
    -r requirements-answer.txt \
    -r requirements-app.txt
COPY streamlit_app.py ./

# Application data is bind-mounted by Compose; do not bake papers or keys into the image.
RUN groupadd --system marine && \
    useradd --system --uid 10001 --gid marine --create-home marine && \
    mkdir -p /app/data/app /app/data/chunks/word_safe /app/papers /app/evaluation && \
    chown -R marine:marine /app
USER marine
