"""
Background worker that processes the subtitle pruning queue.
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
        self.thread: Optional[threading.Thread] = None

        # Load existing queue from disk
        self._load_queue()
    
    def _load_queue(self):
        """Load queue from disk if it exists."""
        if os.path.exists(self.queue_file):
            try:
                with open(self.queue_file, 'r') as f:
                    self.queue = json.load(f)
                logger.info(f"Loaded {len(self.queue)} entries from queue file")
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
        """Add a file to the processing queue."""
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
            # Check if file is already in queue (pending or processing)
            for existing in self.queue:
                if existing['file_path'] == file_path and existing['status'] in ('pending', 'processing'):
                    logger.info(f"File already in queue: {file_path}")
                    return existing
            
            self.queue.append(entry)
            self._save_queue()
        
        return entry
    
    def get_status(self) -> dict:
        """Get current queue status."""
        with self.lock:
            pending = [e for e in self.queue if e['status'] == 'pending']
            processing = [e for e in self.queue if e['status'] == 'processing']
            completed = [e for e in self.queue if e['status'] == 'completed']
            failed = [e for e in self.queue if e['status'] == 'failed']
            skipped = [e for e in self.queue if e['status'] == 'skipped']
            
            return {
                'worker_running': self.running,
                'current_file': self.current_file,
                'counts': {
                    'pending': len(pending),
                    'processing': len(processing),
                    'completed': len(completed),
                    'failed': len(failed),
                    'skipped': len(skipped),
                    'total': len(self.queue)
                },
                'pending': pending[-10:],  # Last 10
                'processing': processing,
                'recent_completed': sorted(completed, key=lambda x: x['completed_at'] or '', reverse=True)[:10],
                'recent_failed': sorted(failed, key=lambda x: x['completed_at'] or '', reverse=True)[:10],
                'recent_skipped': sorted(skipped, key=lambda x: x['completed_at'] or '', reverse=True)[:10]
            }
    
    def clear_history(self) -> int:
        """Clear completed, failed, and skipped entries."""
        with self.lock:
            before = len(self.queue)
            self.queue = [e for e in self.queue if e['status'] in ('pending', 'processing')]
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
        """Start the background worker thread."""
        if self.thread and self.thread.is_alive():
            logger.warning("Worker already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        logger.info("Background worker started")
    
    def stop(self):
        """Stop the background worker."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Background worker stopped")
    
    def _worker_loop(self):
        """Main worker loop - processes queue entries."""
        while self.running:
            entry = self._get_next_pending()
            
            if entry is None:
                # No work to do, sleep a bit
                time.sleep(1)
                continue
            
            self._process_entry(entry)
    
    def _get_next_pending(self) -> Optional[dict]:
        """Get the next pending entry and mark it as processing."""
        with self.lock:
            for entry in self.queue:
                if entry['status'] == 'pending':
                    entry['status'] = 'processing'
                    entry['started_at'] = datetime.now().isoformat()
                    self.current_file = entry['file_path']
                    self._save_queue()
                    return entry
        return None
    
    def _process_entry(self, entry: dict):
        """Process a single queue entry."""
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
