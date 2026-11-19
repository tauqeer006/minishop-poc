FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# 1) wait for replica-set primary + create indexes, 2) idempotent seed, 3) serve.
# Single worker on purpose: dev scenario state and the window monitor are in-process.
CMD ["sh", "-c", "python -m scripts.initialize_database && python -m scripts.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
