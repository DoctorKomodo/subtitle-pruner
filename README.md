# Subtitle Pruner

A webhook-based service that automatically removes unwanted subtitle tracks from MKV files. Designed to integrate with Radarr and Sonarr.

## Features

- **Webhook endpoint** for Radarr/Sonarr integration
- **Web UI** to monitor queue status and processing history
- **Persistent queue** survives container restarts
- **Configurable language filter** via environment variable
- **Scheduled processing** — optionally batch file processing to a specific time of day
- **Safe processing** — writes to temp file, then replaces original
- **PUID/PGID support** — run as any host user for correct file permissions

## Quick Start

### 1. Create a docker-compose.yml

The Docker image is automatically built and published to GitHub Container Registry. Create a `docker-compose.yml` on your server (e.g., Synology NAS):

```yaml
version: "3.8"

services:
  subtitle-pruner:
    image: ghcr.io/doctorkomodo/subtitle-pruner:latest
    container_name: subtitle-pruner
    restart: unless-stopped
    ports:
      - "14000:14000"
    volumes:
      - ./data:/data
      - /volume1/media:/volume1/media  # Adjust to your paths
    environment:
      - PUID=1000
      - PGID=1000
      - ALLOWED_LANGUAGES=eng,dan
      - LOG_LEVEL=INFO
      - PORT=14000
```

**Important:** Set `PUID` and `PGID` to match the host user that owns your media files (find with `id your_user`). The paths inside the container must match the paths that Radarr/Sonarr will send. If Radarr is configured with `/volume1/media/movies` as its root folder, mount exactly that path.

### 2. Run

```bash
docker-compose up -d
```

To update to the latest version:

```bash
docker-compose pull && docker-compose up -d
```

### 3. Verify it's running

Open `http://your-nas-ip:14000` in a browser. You should see the web UI.

### Building locally (optional)

If you prefer to build from source instead of pulling from GHCR:

```bash
git clone https://github.com/DoctorKomodo/subtitle-pruner.git
cd subtitle-pruner
docker-compose up -d --build
```

Replace `image:` with `build: .` in `docker-compose.yml` when building locally.

## Radarr/Sonarr Setup

### Radarr

1. Go to **Settings → Connect**
2. Click **+** and select **Webhook**
3. Configure:
   - **Name:** Subtitle Pruner
   - **On Import:** ✓ (check this)
   - **On Upgrade:** ✓ (check this)
   - **URL:** `http://your-nas-ip:14000/webhook`
   - **Method:** POST
4. Save

### Sonarr

Same steps as Radarr — add a webhook connection pointing to `http://your-nas-ip:14000/webhook`

## Configuration

Environment variables in `docker-compose.yml`:

| Variable | Default | Description |
|----------|---------|-------------|
| `PUID` | `1000` | UID to run as — set to match your host user |
| `PGID` | `1000` | GID to run as — set to match your host user |
| `ALLOWED_LANGUAGES` | `eng,dan` | Comma-separated language codes to keep |
| `LOG_LEVEL` | `INFO` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |
| `PORT` | `14000` | HTTP port |
| `PATH_MAPPINGS` | *(none)* | Path translations (see below) |
| `PROCESS_TIME` | *(none)* | Time of day to process files in HH:MM 24-hour format (see below) |
| `QUEUE_FILE` | `/data/queue.json` | Path to the persistent queue file |

### PUID / PGID

The container uses the LinuxServer.io-style PUID/PGID mechanism. At startup, it creates an internal user matching the specified UID/GID, then drops root privileges. This means the process accesses your media files as your host user — no permission issues with bind mounts.

Find your IDs with:

```bash
id your_user
# uid=1035(your_user) gid=100(users) ...
```

Then set them in `docker-compose.yml`:

```yaml
environment:
  - PUID=1035
  - PGID=100
```

### Language Codes

Use ISO 639-2 three-letter codes. Common examples:
- `eng` - English
- `dan` - Danish
- `swe` - Swedish
- `nor` - Norwegian
- `deu` / `ger` - German
- `fra` / `fre` - French
- `spa` - Spanish
- `jpn` - Japanese

### Path Mappings

If Radarr/Sonarr runs on a different machine (e.g., Windows) and reports paths that don't match the container's filesystem, use `PATH_MAPPINGS` to translate them.

**Format:** `from=to,from2=to2`

**Example:** Radarr on Windows sends UNC paths like `\\diskstation\movies\...`, but the container mounts the share at `/media/movies`:

```yaml
environment:
  - PATH_MAPPINGS=\\diskstation\movies\=/media/movies/,\\diskstation\tvseries\=/media/tv/

volumes:
  - /volume2/movies:/media/movies/
  - /volume2/tvseries:/media/tv/
```

The path `\\diskstation\movies\Film (2024)\film.mkv` becomes `/media/movies/Film (2024)/film.mkv`.

### Process Time

Set `PROCESS_TIME` to batch all file processing to a specific time of day. Files are still analyzed immediately when webhooks arrive, but the actual remuxing is deferred. This is useful to avoid disk I/O during peak hours.

```yaml
environment:
  - PROCESS_TIME=02:00  # Process queued files at 2 AM
```

If not set, files are processed immediately after analysis.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/webhook` | POST | Receive file notifications from Radarr/Sonarr |
| `/api/status` | GET | JSON status of queue and processing |
| `/api/retry/<id>` | POST | Retry a failed entry |
| `/api/queue` | DELETE | Clear completed/failed/skipped history |

## Manual Testing

Test the webhook with curl:

```bash
curl -X POST http://localhost:14000/webhook \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/volume1/media/movies/Test Movie (2024)/Test.Movie.2024.mkv"}'
```

## Processing Logic

For each MKV file:

1. **Read track info** using `mkvmerge --identify`
2. **Identify subtitle tracks** to keep (allowed languages, not forced)
3. **Skip if nothing to remove** (no unwanted subtitles)
4. **Process with mkvmerge** — output to temp file in same folder
5. **Replace original** when complete

### What gets removed

- Subtitle tracks in languages not in `ALLOWED_LANGUAGES`
- Forced subtitle tracks (regardless of language)

### What gets kept

- Subtitle tracks in allowed languages that are not forced
- All video tracks
- All audio tracks
- All other track types (chapters, attachments, etc.)

## Troubleshooting

### Check logs

```bash
docker-compose logs -f
```

### File not found errors

Make sure the volume mounts in `docker-compose.yml` match the paths Radarr/Sonarr are sending. The paths must be identical.

If Radarr/Sonarr runs on a different machine and sends paths the container can't access (e.g., Windows UNC paths like `\\server\share\...`), configure `PATH_MAPPINGS` to translate them to container paths.

### Permission errors

Set `PUID` and `PGID` to match the owner of your media files on the host. See the [PUID / PGID](#puid--pgid) section above.

### Webhook not receiving

1. Check the container is running: `docker-compose ps`
2. Check the port is accessible: `curl http://localhost:14000/api/status`
3. Use Radarr/Sonarr's "Test" button — the service responds with 200 OK to test events

## File Structure

```
subtitle-pruner/
├── app.py              # Flask application, routes
├── worker.py           # Background queue processor
├── processor.py        # MKV subtitle processing logic
├── entrypoint.sh       # PUID/PGID handling and privilege drop
├── templates/
│   └── index.html      # Web UI template
├── requirements.txt    # Python dependencies
├── Dockerfile          # Container definition
├── docker-compose.yml  # Deployment configuration
├── README.md           # This file
└── CLAUDE.md           # Claude Code context
```
