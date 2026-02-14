"""
Background worker that processes the subtitle pruning queue.

Uses two worker threads:
- Analysis thread: scans files sequentially to determine if processing is needed
- Processing thread: remuxes files that need subtitle removal, with configurable delay
"""

import os
import json
import threading
import time
import logging
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Queue entry statuses:
# pending            - waiting to be analyzed
# analyzing          - currently being scanned by the analysis thread
# awaiting_processing - analysis determined subtitles need removal, waiting for processing
# processing         - currently being remuxed by the processing thread
# completed          - subtitles were removed successfully
# skipped            - no processing needed (determined during analysis)
# failed             - an error occurred


class ProcessingWorker:
    """Background worker that processes files from the queue."""

    def __init__(self, processor, queue_file: str, process_delay: int = 0):
        self.processor = processor
        self.queue_file = queue_file
        self.process_delay = process_delay
        self.queue = []
        self.lock = threading.Lock()
        self.running = False
        self.current_file: Optional[str] = None
        self.analyze_thread: Optional[threading.Thread] = None
        self.process_thread: Optional[threading.Thread] = None

        # Load existing queue from disk
        self._load_queue()

    def _load_queue(self):
        """Load queue from disk if it exists."""
        if os.path.exists(self.queue_file):
            try:
                with open(self.queue_file, 'r') as f:
                    self.queue = json.load(f)
                logger.info(f"Loaded {len(self.queue)} entries from queue file")
                # Reset any entries that were mid-flight when the process stopped
                for entry in self.queue:
                    if entry['status'] == 'analyzing':
                        entry['status'] = 'pending'
                    elif entry['status'] == 'processing':
                        entry['status'] = 'awaiting_processing'
            except Exception as e:
                logger.error(f"Failed to load queue file: {e}")
                self.queue = []

    def _save_queue(self):
        """Persist queue to disk."""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.queue_file), exist_ok=True)
            with open(self.queue_file, 'w') as f:
                json.dump(self.queue, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save queue file: {e}")

    def add_to_queue(self, file_path: str) -> dict:
        """Add a file to the analysis queue."""
        entry = {
            'id': str(uuid.uuid4())[:8],
            'file_path': file_path,
            'status': 'pending',
            'added_at': datetime.now().isoformat(),
            'started_at': None,
            'completed_at': None,
            'result': None,
            'error': None
        }

        with self.lock:
            # Check if file is already in queue (pending, analyzing, awaiting, or processing)
            active_statuses = ('pending', 'analyzing', 'awaiting_processing', 'processing')
            for existing in self.queue:
                if existing['file_path'] == file_path and existing['status'] in active_statuses:
                    logger.info(f"File already in queue: {file_path}")
                    return existing

            self.queue.append(entry)
            self._save_queue()

        return entry

    def get_status(self) -> dict:
        """Get current queue status."""
        with self.lock:
            pending = [e for e in self.queue if e['status'] == 'pending']
            analyzing = [e for e in self.queue if e['status'] == 'analyzing']
            awaiting = [e for e in self.queue if e['status'] == 'awaiting_processing']
            processing = [e for e in self.queue if e['status'] == 'processing']
            completed = [e for e in self.queue if e['status'] == 'completed']
            failed = [e for e in self.queue if e['status'] == 'failed']
            skipped = [e for e in self.queue if e['status'] == 'skipped']

            return {
                'worker_running': self.running,
                'current_file': self.current_file,
                'counts': {
                    'pending': len(pending),
                    'analyzing': len(analyzing),
                    'awaiting_processing': len(awaiting),
                    'processing': len(processing),
                    'completed': len(completed),
                    'failed': len(failed),
                    'skipped': len(skipped),
                    'total': len(self.queue)
                },
                'pending': pending[-10:],
                'analyzing': analyzing,
                'awaiting_processing': awaiting[-10:],
                'processing': processing,
                'recent_completed': sorted(completed, key=lambda x: x['completed_at'] or '', reverse=True)[:10],
                'recent_failed': sorted(failed, key=lambda x: x['completed_at'] or '', reverse=True)[:10],
                'recent_skipped': sorted(skipped, key=lambda x: x['completed_at'] or '', reverse=True)[:10]
            }

    def clear_history(self) -> int:
        """Clear completed, failed, and skipped entries."""
        with self.lock:
            before = len(self.queue)
            self.queue = [e for e in self.queue if e['status'] in
                          ('pending', 'analyzing', 'awaiting_processing', 'processing')]
            after = len(self.queue)
            self._save_queue()
            return before - after

    def retry_entry(self, entry_id: str) -> bool:
        """Retry a failed entry."""
        with self.lock:
            for entry in self.queue:
                if entry['id'] == entry_id and entry['status'] in ('failed', 'skipped'):
                    entry['status'] = 'pending'
                    entry['error'] = None
                    entry['result'] = None
                    entry['started_at'] = None
                    entry['completed_at'] = None
                    self._save_queue()
                    return True
        return False

    def start(self):
        """Start the background worker threads."""
        if self.analyze_thread and self.analyze_thread.is_alive():
            logger.warning("Workers already running")
            return

        self.running = True

        self.analyze_thread = threading.Thread(target=self._analyze_loop, daemon=True)
        self.analyze_thread.start()
        logger.info("Analysis worker started")

        self.process_thread = threading.Thread(target=self._process_loop, daemon=True)
        self.process_thread.start()
        logger.info("Processing worker started")

    def stop(self):
        """Stop the background workers."""
        self.running = False
        if self.analyze_thread:
            self.analyze_thread.join(timeout=5)
        if self.process_thread:
            self.process_thread.join(timeout=5)
        logger.info("Background workers stopped")

    # --- Analysis thread ---

    def _analyze_loop(self):
        """Analysis worker loop - scans files to determine if processing is needed."""
        while self.running:
            entry = self._get_next_for_status('pending', 'analyzing')

            if entry is None:
                time.sleep(1)
                continue

            self._analyze_entry(entry)

    def _analyze_entry(self, entry: dict):
        """Analyze a single queue entry."""
        file_path = entry['file_path']
        logger.info(f"Analyzing: {file_path}")

        try:
            analysis = self.processor.analyze_file(file_path)

            with self.lock:
                if not analysis.get('needs_processing'):
                    entry['status'] = 'skipped'
                    entry['completed_at'] = datetime.now().isoformat()
                    entry['result'] = {
                        'action': analysis.get('action', 'skipped'),
                        'reason': analysis.get('reason', 'unknown')
                    }
                    logger.info(f"Skipped: {file_path} - {analysis.get('reason')}")
                else:
                    entry['status'] = 'awaiting_processing'
                    logger.info(f"Queued for processing: {file_path} - "
                                f"{len(analysis['tracks_to_remove'])} tracks to remove")

                self._save_queue()

        except Exception as e:
            logger.exception(f"Failed to analyze {file_path}: {e}")
            with self.lock:
                entry['status'] = 'failed'
                entry['completed_at'] = datetime.now().isoformat()
                entry['error'] = str(e)
                self._save_queue()

    # --- Processing thread ---

    def _process_loop(self):
        """Processing worker loop - remuxes files that need subtitle removal."""
        while self.running:
            entry = self._get_next_for_status('awaiting_processing', 'processing')

            if entry is None:
                time.sleep(1)
                continue

            self._process_entry(entry)

    def _process_entry(self, entry: dict):
        """Process a single queue entry that needs subtitle removal."""
        file_path = entry['file_path']

        if self.process_delay > 0:
            logger.info(f"Waiting {self.process_delay}s before processing: {file_path}")
            time.sleep(self.process_delay)

        logger.info(f"Processing: {file_path}")

        try:
            result = self.processor.process_file(file_path)

            with self.lock:
                entry['completed_at'] = datetime.now().isoformat()
                entry['result'] = result

                if result['action'] == 'processed':
                    entry['status'] = 'completed'
                    logger.info(f"Completed: {file_path} - removed {result.get('removed_tracks', 0)} tracks")
                elif result['action'] == 'skipped':
                    entry['status'] = 'skipped'
                    logger.info(f"Skipped: {file_path} - {result.get('reason', 'unknown')}")
                else:
                    entry['status'] = 'completed'

                self.current_file = None
                self._save_queue()

        except Exception as e:
            logger.exception(f"Failed to process {file_path}: {e}")

            with self.lock:
                entry['status'] = 'failed'
                entry['completed_at'] = datetime.now().isoformat()
                entry['error'] = str(e)
                self.current_file = None
                self._save_queue()

    # --- Shared helpers ---

    def _get_next_for_status(self, from_status: str, to_status: str) -> Optional[dict]:
        """Get the next entry with from_status and transition it to to_status."""
        with self.lock:
            for entry in self.queue:
                if entry['status'] == from_status:
                    entry['status'] = to_status
                    entry['started_at'] = datetime.now().isoformat()
                    if to_status == 'processing':
                        self.current_file = entry['file_path']
                    self._save_queue()
                    return entry
        return None
