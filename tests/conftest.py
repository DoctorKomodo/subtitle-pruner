"""Shared test fixtures for subtitle-pruner tests."""

import os
import json
import pytest

# Set TESTING before importing app to prevent module-level side effects
# (mkvmerge verification, worker thread spawning)
os.environ['TESTING'] = '1'

from app import app, CONFIG
from worker import ProcessingWorker


class FakeProcessor:
    """No-op processor for tests that don't need real mkvmerge."""

    def analyze_file(self, path):
        return {'needs_processing': False, 'action': 'skipped', 'reason': 'test'}

    def process_file(self, path):
        return {'action': 'skipped', 'reason': 'test'}


@pytest.fixture
def mock_worker(tmp_path):
    """A real ProcessingWorker with a temp queue file and a no-op processor.

    Threads are NOT started — only queue operations are available.
    """
    queue_file = str(tmp_path / 'queue.json')
    w = ProcessingWorker(FakeProcessor(), queue_file, '')
    return w


@pytest.fixture
def client_with_worker(mock_worker):
    """Flask test client with a real (but threadless) worker injected."""
    import app as app_module
    original_worker = app_module.worker
    app_module.worker = mock_worker
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c, mock_worker
    app_module.worker = original_worker
