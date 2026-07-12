# Backend (FastAPI + Patchright/Chromium) for a container host (Hugging Face
# Spaces, Render, Fly, etc). The Playwright base image ships Chromium's system
# libraries, which Patchright needs; a plain python image would be missing them.
FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

WORKDIR /app

# Install Python deps first for layer caching.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Patchright's own patched Chromium build.
RUN python -m patchright install chromium

# Only the backend runs in the image; frontend is deployed separately (Vercel).
COPY backend/ .

# Writable caches for HF Spaces (HOME may be read-only otherwise).
ENV LLM_PROVIDER=openai \
    DEFAULT_MODEL=gpt-4o-mini \
    COOKIE_SECURE=1 \
    COOKIE_SAMESITE=lax \
    PORT=7860 \
    HOME=/app \
    TEMP=/tmp

# Shell form so ${PORT} expands. PORT defaults to 7860; hosts override it.
# IMPORTANT: run a SINGLE worker. Background jobs (JOBS) and the session cache
# live in this process's memory; a second worker cannot see them, so job polling
# would miss in-flight work. Scale by running one bigger box, not more workers
# (move JOBS to Redis/Postgres first if you ever need multiple workers).
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT} --workers 1
