FROM python:3.13-alpine

# Install mkvtoolnix
RUN apk add --no-cache mkvtoolnix

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py worker.py processor.py ./
COPY templates/ ./templates/

# Create non-root user and data directory
RUN adduser -D -h /app appuser && \
    mkdir -p /data && \
    chown appuser:appuser /data

# Environment defaults
ENV PORT=14000
ENV ALLOWED_LANGUAGES=eng,dan
ENV QUEUE_FILE=/data/queue.json
ENV LOG_LEVEL=INFO
ENV ALLOWED_PATHS=/media

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 14000

# Run with gunicorn (production WSGI server)
CMD ["gunicorn", "--bind", "0.0.0.0:14000", "--workers", "1", "--threads", "2", "--timeout", "120", "app:app"]
