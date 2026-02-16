FROM python:3.13-alpine

# Install mkvtoolnix and su-exec (lightweight privilege drop, like gosu)
RUN apk add --no-cache mkvtoolnix su-exec

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and entrypoint
COPY app.py worker.py processor.py ./
COPY templates/ ./templates/
COPY entrypoint.sh /entrypoint.sh

# Create non-root user and data directory
RUN adduser -D -h /app appuser && \
    mkdir -p /data && \
    chown appuser:appuser /data

# Environment defaults
ENV PORT=14000
ENV ALLOWED_LANGUAGES=eng,dan
ENV QUEUE_FILE=/data/queue.json
ENV LOG_LEVEL=INFO
ENV PUID=1000
ENV PGID=1000

# Expose port
EXPOSE 14000

# Entrypoint handles PUID/PGID and drops privileges
ENTRYPOINT ["/entrypoint.sh"]

# Run with gunicorn (production WSGI server)
CMD ["gunicorn", "--bind", "0.0.0.0:14000", "--workers", "1", "--threads", "2", "--timeout", "120", "app:app"]
