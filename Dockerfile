# COMEBACK — the control room as a container (offline mode: committed LLM cache + neural audio).
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LLM_MODE=offline

COPY requirements.txt .
RUN sed '/^# Dev/,$d' requirements.txt > runtime.txt && pip install --no-cache-dir -r runtime.txt

COPY comeback ./comeback
COPY web ./web
COPY data ./data
COPY scripts ./scripts

# Precompute the audience scaling curve so the first visitor does not wait for it.
RUN python scripts/scale_cache.py

EXPOSE 8000
CMD ["python", "-m", "comeback", "--port", "8000"]
