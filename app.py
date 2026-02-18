"""
Subtitle Pruner - Flask application with webhook endpoint and web UI
Receives notifications from Radarr/Sonarr and queues MKV files for subtitle processing.
"""

import os
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from worker import ProcessingWorker
from processor import SubtitleProcessor

# Configuration from environment
CONFIG = {
    'allowed_languages': os.environ.get('ALLOWED_LANGUAGES', 'eng,dan').split(','),
    'queue_file': os.environ.get('QUEUE_FILE', '/data/queue.json'),
    'log_level': os.environ.get('LOG_LEVEL', 'INFO'),
    'path_mappings': [],
    'process_time': os.environ.get('PROCESS_TIME', ''),
}

# Parse PATH_MAPPINGS: "from1=to1,from2=to2" format
path_mappings_raw = os.environ.get('PATH_MAPPINGS', '')
if path_mappings_raw:
    for mapping in path_mappings_raw.split(','):
        if '=' in mapping:
            from_path, to_path = mapping.split('=', 1)
            CONFIG['path_mappings'].append((from_path, to_path))

# Set up logging
logging.basicConfig(
    level=getattr(logging, CONFIG['log_level']),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def apply_path_mapping(file_path: str) -> str:
    """Apply configured path mappings to translate remote paths to local paths."""
    original_path = file_path
    for from_path, to_path in CONFIG['path_mappings']:
        if file_path.startswith(from_path):
            file_path = to_path + file_path[len(from_path):]
            # Normalize path separators to Unix style
            file_path = file_path.replace('\\', '/')
            logger.debug(f"Path mapped: {original_path} -> {file_path}")
            break
    return file_path


# Initialize Flask app
app = Flask(__name__)

# Initialize processor and worker (skipped during testing)
if not os.environ.get('TESTING'):
    processor = SubtitleProcessor(CONFIG['allowed_languages'])
    worker = ProcessingWorker(processor, CONFIG['queue_file'], CONFIG['process_time'])
else:
    processor = None
    worker = None


@app.route('/')
def index():
    """Web UI showing queue status and processing history."""
    status = worker.get_status()
    return render_template('index.html', status=status, config=CONFIG)


@app.route('/api/status')
def api_status():
    """JSON endpoint for queue and processing status."""
    return jsonify(worker.get_status())


@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Webhook endpoint for Radarr/Sonarr.
    
    Radarr sends: movieFile.path or movieFile.relativePath
    Sonarr sends: episodeFile.path or episodeFile.relativePath
    
    Also accepts a simple JSON body: {"file_path": "/path/to/file.mkv"}
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        logger.debug(f"Received webhook payload: {json.dumps(data, indent=2)}")

        # Handle test events from Radarr/Sonarr
        if data.get('eventType') == 'Test':
            logger.info(f"Received test webhook from {data.get('instanceName', 'unknown')}")
            return jsonify({
                'status': 'ok',
                'message': 'Test webhook received successfully'
            }), 200

        # Try to extract file path from various payload formats
        file_path = None
        
        # Simple format: {"file_path": "..."}
        if 'file_path' in data:
            file_path = data['file_path']
        
        # Radarr format
        elif 'movieFile' in data:
            file_path = data['movieFile'].get('path') or data['movieFile'].get('relativePath')
        
        # Sonarr format
        elif 'episodeFile' in data:
            file_path = data['episodeFile'].get('path') or data['episodeFile'].get('relativePath')
        
        # Alternative Radarr/Sonarr formats (varies by version)
        elif 'movie' in data and 'movieFile' in data.get('movie', {}):
            file_path = data['movie']['movieFile'].get('path')
        
        elif 'episodes' in data and len(data.get('episodes', [])) > 0:
            # Sonarr sometimes sends episodes array
            episode = data['episodes'][0]
            if 'episodeFile' in episode:
                file_path = episode['episodeFile'].get('path')
        
        if not file_path:
            logger.warning(f"Could not extract file path from payload: {data}")
            return jsonify({
                'status': 'error',
                'message': 'Could not extract file path from payload'
            }), 400

        # Apply path mappings (e.g., Windows UNC paths to container paths)
        file_path = apply_path_mapping(file_path)

        # Validate it's an MKV file
        if not file_path.lower().endswith('.mkv'):
            logger.info(f"Ignoring non-MKV file: {file_path}")
            return jsonify({
                'status': 'ignored',
                'message': 'Not an MKV file'
            }), 200
        
        # Add to queue
        queue_entry = worker.add_to_queue(file_path)
        logger.info(f"Added to queue: {file_path}")
        
        return jsonify({
            'status': 'queued',
            'message': f'File added to queue',
            'entry': queue_entry
        }), 202
        
    except Exception as e:
        logger.exception(f"Error processing webhook: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/api/queue', methods=['DELETE'])
def clear_history():
    """Clear completed/failed entries from the queue."""
    cleared = worker.clear_history()
    return jsonify({
        'status': 'ok',
        'cleared': cleared
    })


@app.route('/api/retry/<entry_id>', methods=['POST'])
def retry_entry(entry_id):
    """Retry a failed entry."""
    success = worker.retry_entry(entry_id)
    if success:
        return jsonify({'status': 'ok', 'message': 'Entry requeued'})
    else:
        return jsonify({'status': 'error', 'message': 'Entry not found'}), 404


def _start_worker():
    """Log configuration and start the background worker threads."""
    logger.info(f"Starting Subtitle Pruner")
    logger.info(f"Allowed languages: {CONFIG['allowed_languages']}")
    if CONFIG['process_time']:
        logger.info(f"Process time: {CONFIG['process_time']}")
    else:
        logger.info("No process time configured - files will be processed immediately")
    if CONFIG['path_mappings']:
        logger.info(f"Path mappings configured:")
        for from_path, to_path in CONFIG['path_mappings']:
            logger.info(f"  {from_path} -> {to_path}")
    else:
        logger.info("No path mappings configured")

    worker.start()


# Start worker threads when the module is loaded (works with both gunicorn and direct run)
if not os.environ.get('TESTING'):
    _start_worker()


if __name__ == '__main__':
    # Development only — use gunicorn in production
    port = int(os.environ.get('PORT', 14000))
    app.run(host='0.0.0.0', port=port, debug=False)
