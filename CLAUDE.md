# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Subtitle Pruner is a webhook-based service that automatically removes unwanted subtitle tracks from MKV files. It integrates with Radarr/Sonarr via webhooks.

## Development Commands

### Running with Docker (primary method)
```bash
docker-compose up -d --build    # Build and run
docker-compose logs -f          # View logs
docker-compose ps               # Check status
```

### Running locally (for development)
```bash
pip install -r requirements.txt
python app.py
```

Requires `mkvtoolnix` to be installed for `mkvmerge` command.

### Testing the webhook
```bash
curl -X POST http://localhost:14000/webhook \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/path/to/file.mkv"}'
```

## Architecture

The application has three main components:

1. **app.py** - Flask web application
   - `/webhook` endpoint receives POST requests from Radarr/Sonarr
   - `/api/status` returns queue state as JSON
   - `/` serves the web UI
   - Parses multiple payload formats (Radarr, Sonarr, simple `file_path`)
   - Handles test events from Radarr/Sonarr (returns 200 OK)
   - Applies path mappings via `apply_path_mapping()` to translate remote paths

2. **worker.py** - Background queue processor (`ProcessingWorker`)
   - Runs in a daemon thread started by `app.py`
   - Persists queue to `/data/queue.json` for restart recovery
   - Thread-safe queue operations using `threading.Lock`
   - Processes files sequentially from the queue
   - Supports configurable delay before processing (`PROCESS_DELAY`)

3. **processor.py** - MKV processing logic (`SubtitleProcessor`)
   - Uses `mkvmerge --identify` to read track metadata
   - Keeps subtitle tracks that match allowed languages AND are not forced
   - Writes to `.tmp.mkv` then replaces original atomically
   - Has sanity check: fails if output is <50% of original size

## Key Configuration

Environment variables (set in `docker-compose.yml`):
- `ALLOWED_LANGUAGES` - Comma-separated ISO 639-2 codes (default: `eng,dan`)
- `LOG_LEVEL` - DEBUG, INFO, WARNING, ERROR
- `PORT` - HTTP port (default: 14000)
- `QUEUE_FILE` - Path to queue persistence file
- `PATH_MAPPINGS` - Translate remote paths to container paths (format: `from1=to1,from2=to2`)
- `PROCESS_DELAY` - Seconds to wait before processing a file (default: 0)

## Processing Flow

1. Radarr/Sonarr sends webhook on import/upgrade (test events return 200 OK immediately)
2. `app.py` extracts file path, applies path mappings, validates `.mkv` extension, adds to queue
3. Worker picks up entry, marks as "processing", waits for `PROCESS_DELAY` if configured
4. `SubtitleProcessor.process_file()`:
   - Reads tracks with `mkvmerge --identify --identification-format json`
   - Filters subtitle tracks: keeps if language in allowed list AND not forced
   - If nothing to remove: marks as "skipped"
   - Runs `mkvmerge --output temp.mkv --subtitle-tracks <keep_ids> input.mkv`
   - Replaces original with `os.replace()`
5. Queue entry marked completed/failed/skipped with result details
