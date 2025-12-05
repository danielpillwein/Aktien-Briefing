# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .

RUN pip install --no-cache-dir --target=/build/deps -r requirements.txt


# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Copy dependencies from builder
COPY --from=builder /build/deps /usr/local/lib/python3.11/site-packages/

# Copy application files
COPY main.py .
COPY config/ ./config/
COPY core/ ./core/
COPY utils/ ./utils/
COPY templates/ ./templates/

# Create directories for runtime data
RUN mkdir -p cache data outputs archive logs

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["python", "main.py"]
