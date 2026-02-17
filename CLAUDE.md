# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Subtitle Pruner is a webhook-based service that automatically removes unwanted subtitle tracks from MKV files. It integrates with Radarr/Sonarr via webhooks and provides a web UI for monitoring the processing queue.

## CRITICAL

RESPECT THE WORKFLOW BELOW!!!
NEVER: leave uncommitted or unpushed changes - always maintain a consistent and backed-up repository state
ALWAYS: Consider if a web research for current best practices could be useful.
ALWAYS: Consider if a web research for existing framework components that cover the requirements

## WORKFLOW

### Git Branching

Work on feature branches, NOT directly on main/master
Create a new branch for each task: `git checkout -b feature/<descriptive-name>`
Commit changes to the feature branch with conventional commit messages
Only merge to main when the user approves the changes
After merge approval: merge to main with `--no-ff`, push, and delete the feature branch
Keep feature branches focused on a single task/feature

### Code Review Process

After completing a task do two subsequent reviews:
First: review your changes with a subagent that focuses on the big picture, how the new implementation is used and which implications arise
Second: review your changes with a subagent the default way
Address findings and ask back if anything unclear.

## Repository Structure

```
subtitle-pruner/
├── app.py                        # Flask web application (entry point)
├── worker.py                     # Background queue processor (two threads)
├── processor.py                  # MKV subtitle pruning logic via mkvmerge
├── entrypoint.sh                 # Container entrypoint for PUID/PGID handling
├── templates/
│   └── index.html               # Web UI dashboard (Jinja2, dark theme, auto-refresh)
├── requirements.txt              # Pinned Python dependencies
├── Dockerfile                    # python:3.13-alpine, installs mkvtoolnix + su-exec
├── docker-compose.yml            # Example deployment configuration
├── .github/
│   └── workflows/
│       └── docker-publish.yml   # CI: builds & pushes to GHCR on every push/tag
└── README.md                     # User-facing documentation
```

## Architecture

The application has three main components:

### 1. `app.py` — Flask Web Application

- **`/`** — Web UI dashboard (rendered by `templates/index.html`)
- **`/webhook`** (POST) — Receives events from Radarr/Sonarr
- **`/api/status`** (GET) — Returns queue state as JSON
- **`/api/queue`** (DELETE) — Clears completed/failed/skipped history
- **`/api/retry/<entry_id>`** (POST) — Requeues a failed/skipped entry

Key behaviours:
- Parses multiple webhook payload formats: simple `{"file_path": "..."}`, Radarr (`movieFile.path`), Sonarr (`episodeFile.path`), and variant/nested formats
- Returns `200 OK` immediately for `eventType == 'Test'` events from Radarr/Sonarr
- Applies path mappings via `apply_path_mapping()` — translates remote paths (e.g. Windows UNC) to container paths
- Validates `.mkv` extension; ignores other file types with `200 ignored`
- Prevents duplicate queue entries for files already in an active status
- Worker threads are started at module load time via `_start_worker()` — works with both gunicorn and direct `python app.py`

### 2. `worker.py` — `ProcessingWorker` Class

Runs two long-lived daemon threads:

**Analysis thread** (`_analyze_loop`):
- Polls queue for `pending` entries, transitions them to `analyzing`
- Calls `processor.analyze_file()` to scan track info
- Marks as `skipped` (no processing needed) or `awaiting_processing`
- On error: marks as `failed`

**Processing thread** (`_process_loop`):
- Two modes depending on `PROCESS_TIME` env var:
  - **Immediate** (no `PROCESS_TIME`): processes `awaiting_processing` entries as they appear
  - **Scheduled** (`PROCESS_TIME` set): waits until configured time of day, then batch-processes all queued files
- Calls `processor.process_file()` for actual remuxing
- On error: marks as `failed`

Other responsibilities:
- Persists queue to `/data/queue.json` after every state change
- On startup, resets `analyzing` → `pending` and `processing` → `awaiting_processing` (crash recovery)
- Prevents duplicate active entries in `add_to_queue()`
- `get_status()` returns paginated, sorted views for the UI (last 10 completed/failed/skipped)

**Queue entry lifecycle:**
```
pending → analyzing → skipped
                    → awaiting_processing → processing → completed
                                                       → failed
failed / skipped → pending  (via retry)
```

**Queue entry fields:**
```json
{
  "id": "<8-char uuid prefix>",
  "file_path": "/path/to/file.mkv",
  "status": "pending|analyzing|awaiting_processing|processing|completed|skipped|failed",
  "added_at": "<ISO timestamp>",
  "started_at": "<ISO timestamp or null>",
  "completed_at": "<ISO timestamp or null>",
  "result": { ... },
  "error": "<string or null>"
}
```

### 3. `processor.py` — `SubtitleProcessor` Class

Wraps `mkvmerge` from the `mkvtoolnix` package.

**`analyze_file(file_path)`** — determines whether processing is needed:
- Checks file existence and `.mkv` extension
- Reads track metadata via `mkvmerge --identify --identification-format json`
- Filters subtitle tracks: **keeps** tracks where `language in allowed_languages AND NOT forced_track`
- Returns early (skipped) if: no subtitle tracks, nothing to remove, or nothing would remain
- Logs a warning if all subtitle tracks would be removed (safety guard)

**`process_file(file_path)`** — performs the actual remux:
1. Calls `analyze_file()` first
2. Builds `mkvmerge --output <temp> --subtitle-tracks <keep_ids> <input>` command
3. Temp file is created in the same directory as the original, named `<basename>.mkv.tmp`
4. mkvmerge exit codes: `0` = success, `1` = warnings (logged), `2` = error (raises)
5. Sanity check: aborts if output is less than 50% of original size
6. Atomically replaces original with `os.replace(temp, original)`
7. Cleans up temp file on any failure

## Key Configuration

Environment variables (set in `docker-compose.yml` or container environment):

| Variable | Default | Description |
|---|---|---|
| `ALLOWED_LANGUAGES` | `eng,dan` | Comma-separated ISO 639-2 language codes to keep |
| `LOG_LEVEL` | `INFO` | Python logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `PORT` | `14000` | HTTP port |
| `QUEUE_FILE` | `/data/queue.json` | Path to queue persistence file |
| `PATH_MAPPINGS` | _(empty)_ | Path translations: `from1=to1,from2=to2` (comma-separated) |
| `PROCESS_TIME` | _(empty)_ | HH:MM 24-hour time to batch-process files. Empty = immediate. |
| `PUID` | `1000` | Host user ID the container process runs as |
| `PGID` | `1000` | Host group ID the container process runs as |

### `PATH_MAPPINGS` format

Translates the `from` prefix to `to` prefix. Applied once per file path (first match wins). Path separators are normalised to Unix `/` after mapping.

```
PATH_MAPPINGS=\\diskstation\movies\=/media/movies/,\\diskstation\tvseries\=/media/tv/
```

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

Requires `mkvtoolnix` to be installed locally for the `mkvmerge` command.

### Testing the webhook

Simple format:
```bash
curl -X POST http://localhost:14000/webhook \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/path/to/file.mkv"}'
```

Simulate a Radarr webhook:
```bash
curl -X POST http://localhost:14000/webhook \
  -H "Content-Type: application/json" \
  -d '{"eventType": "Download", "movieFile": {"path": "/media/movies/Film.mkv"}}'
```

Simulate a test event (returns 200 immediately):
```bash
curl -X POST http://localhost:14000/webhook \
  -H "Content-Type: application/json" \
  -d '{"eventType": "Test", "instanceName": "Radarr"}'
```

Check status:
```bash
curl http://localhost:14000/api/status
```

## Container / Entrypoint

`entrypoint.sh` implements the LinuxServer.io PUID/PGID pattern:
1. Removes the build-time `appuser`
2. Reuses existing group/user if the target GID/UID already exists in `/etc/group` or `/etc/passwd`
3. Otherwise creates `appuser` with the specified IDs
4. Sets ownership of `/data` to the resolved user/group
5. Uses `su-exec` to drop privileges before executing `CMD`

The Dockerfile runs gunicorn with 1 worker and 2 threads (`--workers 1 --threads 2 --timeout 120`). The single-worker constraint is intentional — the in-memory queue and threading model assumes a single process.

## CI/CD

`.github/workflows/docker-publish.yml` triggers on:
- Any branch push (produces a branch-name tag)
- Tags matching `v*` (produces semver tags + `latest` on default branch)
- Manual `workflow_dispatch`

Images are pushed to `ghcr.io/doctorkomodo/subtitle-pruner`.

## Frontend

`templates/index.html` is a single-page Jinja2 template:
- Dark theme CSS using CSS custom properties
- Stats cards: Analyzing, Processing, Completed, Skipped, Failed
- Live queue sections: currently processing (spinner), analyzing, awaiting, completed/skipped/failed (last 10 each)
- Retry button on failed entries (calls `/api/retry/<id>`)
- Clear History button (calls `DELETE /api/queue`)
- Auto-refreshes every 5 seconds via `setTimeout(() => window.location.reload(), 5000)`

## Key Implementation Details & Conventions

### Thread safety
All queue mutations go through `self.lock` (a `threading.Lock`). `_save_queue()` is always called **inside** the lock, immediately after every mutation. Any new queue operation you add must follow this pattern — failing to call `_save_queue()` inside the lock causes disk state to diverge.

### No test suite
There are no automated unit or integration tests. When adding features, test manually via curl and the web UI before committing.

### Single-worker gunicorn constraint — IMPORTANT
Gunicorn is configured with `--workers 1`. **Do not increase this.** The processing queue lives in-process memory (`ProcessingWorker.queue`). Multiple workers would each maintain a separate queue instance, breaking deduplication, state tracking, and file persistence. The two-thread design (analysis + processing) inside the single worker is intentional.

### `current_file` tracks processing only
`ProcessingWorker.current_file` is set only when a file transitions to `processing` status (not during analysis). The web UI displays it under "Currently Processing". It is `None` while the analysis thread is running.

### Duplicate detection scope
`add_to_queue()` only deduplicates against entries in active statuses (`pending`, `analyzing`, `awaiting_processing`, `processing`). Files that previously completed, were skipped, or failed will be re-queued without issue — this is intentional to allow re-processing after file changes or retries.

### Extending webhook payload parsing
Add new payload extraction branches inside the `webhook()` function in `app.py`, before the `if not file_path` guard. Follow the existing pattern of extracting `file_path` from nested dict keys.

### Adding new environment variables
1. Read in `app.py` at module level, add to the `CONFIG` dict
2. Pass into `ProcessingWorker` or `SubtitleProcessor` constructor as needed
3. Document in `docker-compose.yml` and this file

### Error handling conventions
- `analyze_file()` returns a dict with `needs_processing: False` for non-fatal cases (file not found, no subtitles, track-read exception) — it does **not** raise
- `process_file()` raises on fatal errors; the worker catches and marks the entry `failed`
- `subprocess.run` calls always have explicit `timeout` values set

### mkvmerge behaviour
- Exit code `0`: success
- Exit code `1`: warnings only — output file is still created and valid; warnings are logged but processing continues normally
- Exit code `2`: error (raises `RuntimeError`); temp file is cleaned up
- The `--subtitle-tracks` flag takes a comma-separated list of track IDs to **include**; all other subtitle tracks are dropped automatically
- `analyze_file()` returns early (skipped) if no allowed subtitle tracks would remain after filtering — this prevents mkvmerge from running with an empty `keep_ids` which would silently remove all subtitles

## Processing Flow Summary

1. Radarr/Sonarr fires webhook → `POST /webhook`
2. `app.py` extracts file path, applies path mappings, validates `.mkv`, deduplicates, adds as `pending`
3. **Analysis thread** picks up `pending` → calls `analyze_file()`:
   - Nothing to remove → `skipped`
   - Tracks need removal → `awaiting_processing`
   - Exception → `failed`
4. **Processing thread** picks up `awaiting_processing`:
   - If `PROCESS_TIME` set: waits until scheduled time, then batch-processes
   - Otherwise: processes immediately
   - Calls `process_file()` → remuxes → `completed` or `failed`
5. UI refreshes every 5s showing current state
