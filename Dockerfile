# Backend (FastAPI + Patchright/Chromium) for Render.
# The Playwright base image ships Chromium's system libraries, which Patchright
# needs; a plain python image would be missing them.
FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

WORKDIR /app

# Install Python deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Patchright's own patched Chromium build.
RUN python -m patchright install chromium

COPY . .

ENV LLM_PROVIDER=openai \
    DEFAULT_MODEL=gpt-4o-mini \
    COOKIE_SECURE=1 \
    PORT=8000

# Shell form so ${PORT} (set by Render) expands.
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT}
