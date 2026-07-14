FROM python:3.11-slim

WORKDIR /app

# Celery's `-A` app-loader only puts the CWD on sys.path *temporarily* while
# it imports the app module, then removes it. Anything imported later at
# task-run time (e.g. lazy `from modules...` imports inside task bodies)
# then fails with ModuleNotFoundError. Setting PYTHONPATH makes /app a
# permanent, unconditional part of sys.path for every process (uvicorn,
# celery worker, celery beat) regardless of how each one bootstraps.
ENV PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]