"""Tests for ProcessingWorker queue operations (no threads)."""

import json


class TestAddToQueue:
    def test_adds_entry_with_correct_fields(self, mock_worker):
        entry = mock_worker.add_to_queue('/media/test.mkv')
        assert entry['file_path'] == '/media/test.mkv'
        assert entry['status'] == 'pending'
        assert entry['id'] is not None
        assert len(entry['id']) == 8

    def test_duplicate_active_file_returns_existing(self, mock_worker):
        entry1 = mock_worker.add_to_queue('/media/test.mkv')
        entry2 = mock_worker.add_to_queue('/media/test.mkv')
        assert entry1['id'] == entry2['id']

    def test_different_files_get_different_entries(self, mock_worker):
        entry1 = mock_worker.add_to_queue('/media/a.mkv')
        entry2 = mock_worker.add_to_queue('/media/b.mkv')
        assert entry1['id'] != entry2['id']

    def test_persists_to_disk(self, mock_worker):
        mock_worker.add_to_queue('/media/test.mkv')
        with open(mock_worker.queue_file, 'r') as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]['file_path'] == '/media/test.mkv'


class TestGetStatus:
    def test_empty_queue_status(self, mock_worker):
        status = mock_worker.get_status()
        assert status['counts']['total'] == 0
        assert status['worker_running'] is False
        assert status['current_file'] is None

    def test_status_counts_pending(self, mock_worker):
        mock_worker.add_to_queue('/media/test.mkv')
        status = mock_worker.get_status()
        assert status['counts']['pending'] == 1


class TestClearHistory:
    def test_clears_completed_failed_skipped(self, mock_worker):
        mock_worker.add_to_queue('/media/a.mkv')
        mock_worker.add_to_queue('/media/b.mkv')
        mock_worker.add_to_queue('/media/c.mkv')  # pending — should NOT be cleared
        with mock_worker.lock:
            mock_worker.queue[0]['status'] = 'completed'
            mock_worker.queue[1]['status'] = 'failed'
        cleared = mock_worker.clear_history()
        assert cleared == 2
        assert len(mock_worker.queue) == 1
        assert mock_worker.queue[0]['status'] == 'pending'


class TestRetryEntry:
    def test_retry_failed_entry_resets_to_pending(self, mock_worker):
        entry = mock_worker.add_to_queue('/media/test.mkv')
        with mock_worker.lock:
            entry['status'] = 'failed'
            entry['error'] = 'some error'
        result = mock_worker.retry_entry(entry['id'])
        assert result is True
        assert entry['status'] == 'pending'
        assert entry['error'] is None

    def test_retry_skipped_entry_resets_to_pending(self, mock_worker):
        entry = mock_worker.add_to_queue('/media/test.mkv')
        with mock_worker.lock:
            entry['status'] = 'skipped'
        result = mock_worker.retry_entry(entry['id'])
        assert result is True
        assert entry['status'] == 'pending'

    def test_retry_nonexistent_returns_false(self, mock_worker):
        assert mock_worker.retry_entry('nonexist') is False

    def test_retry_pending_entry_returns_false(self, mock_worker):
        entry = mock_worker.add_to_queue('/media/test.mkv')
        assert mock_worker.retry_entry(entry['id']) is False


class TestRequeue:
    def test_completed_file_can_be_requeued(self, mock_worker):
        """Files that completed previously can be re-added as new entries."""
        entry1 = mock_worker.add_to_queue('/media/test.mkv')
        with mock_worker.lock:
            entry1['status'] = 'completed'
        entry2 = mock_worker.add_to_queue('/media/test.mkv')
        assert entry2['id'] != entry1['id']
        assert entry2['status'] == 'pending'

    def test_failed_file_can_be_requeued(self, mock_worker):
        """Files that failed previously can be re-added as new entries."""
        entry1 = mock_worker.add_to_queue('/media/test.mkv')
        with mock_worker.lock:
            entry1['status'] = 'failed'
        entry2 = mock_worker.add_to_queue('/media/test.mkv')
        assert entry2['id'] != entry1['id']
        assert entry2['status'] == 'pending'


class TestQueueRecovery:
    def test_analyzing_reset_to_pending_on_load(self, tmp_path):
        """Crash recovery: entries stuck in 'analyzing' reset to 'pending'."""
        from tests.conftest import FakeProcessor
        queue_file = str(tmp_path / 'queue.json')
        with open(queue_file, 'w') as f:
            json.dump([{
                'id': 'test1234',
                'file_path': '/media/test.mkv',
                'status': 'analyzing',
                'added_at': '2024-01-01T00:00:00',
                'started_at': None,
                'completed_at': None,
                'result': None,
                'error': None
            }], f)

        from worker import ProcessingWorker
        w = ProcessingWorker(FakeProcessor(), queue_file, '')
        assert w.queue[0]['status'] == 'pending'

    def test_processing_reset_to_awaiting_on_load(self, tmp_path):
        """Crash recovery: entries stuck in 'processing' reset to 'awaiting_processing'."""
        from tests.conftest import FakeProcessor
        queue_file = str(tmp_path / 'queue.json')
        with open(queue_file, 'w') as f:
            json.dump([{
                'id': 'test5678',
                'file_path': '/media/test.mkv',
                'status': 'processing',
                'added_at': '2024-01-01T00:00:00',
                'started_at': None,
                'completed_at': None,
                'result': None,
                'error': None
            }], f)

        from worker import ProcessingWorker
        w = ProcessingWorker(FakeProcessor(), queue_file, '')
        assert w.queue[0]['status'] == 'awaiting_processing'
