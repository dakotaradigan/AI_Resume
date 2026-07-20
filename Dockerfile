FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user: the app binds a high port and only needs to write
# under /app/backend/analytics, so root buys nothing and widens blast radius.
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

WORKDIR /app/backend

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
