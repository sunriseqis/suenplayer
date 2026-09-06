# suenplayer backend (APP_VERSION 2.1)
# Build:  docker build -t suenplayer-backend .
# Run:    docker run -p 8080:8080 -v suenplayer_data:/app/data suenplayer-backend
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py config.py quick.py ./

# Run as an unprivileged user; /app/data holds the SQLite database,
# settings and downloaded files and must be writable by the app.
RUN useradd --system --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

VOLUME ["/app/data"]
EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
