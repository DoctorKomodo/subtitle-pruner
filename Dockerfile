FROM python:3.13-alpine

# Install mkvtoolnix
RUN apk add --no-cache mkvtoolnix

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py worker.py processor.py plex.py ./
COPY templates/ ./templates/

# Create data directory for queue persistence
RUN mkdir -p /data

# Environment defaults
ENV PORT=14000
ENV ALLOWED_LANGUAGES=eng,dan
ENV QUEUE_FILE=/data/queue.json
ENV LOG_LEVEL=INFO

# Expose port
EXPOSE 14000

# Run the application
CMD ["python", "app.py"]
