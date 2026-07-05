# Backend (FastAPI + Patchright/Chromium) for a container host (Hugging Face
# Spaces, Render, Fly, etc). The Playwright base image ships Chromium's system
# libraries, which Patchright needs; a plain python image would be missing them.
FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

WORKDIR /app

# Install Python deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Patchright's own patched Chromium build.
RUN python -m patchright install chromium

COPY . .

# Writable caches for HF Spaces (HOME may be read-only otherwise).
ENV LLM_PROVIDER=openai \
    DEFAULT_MODEL=gpt-4o-mini \
    COOKIE_SECURE=1 \
    COOKIE_SAMESITE=lax \
    PORT=7860 \
    HOME=/app \
    TEMP=/tmp

# Shell form so ${PORT} expands. Defaults to 7860 (Hugging Face); Render/Fly
# override PORT with their own value.
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT}
