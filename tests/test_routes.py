"""Tests for non-webhook Flask routes."""


class TestIndexRoute:
    def test_index_returns_200(self, client_with_worker):
        client, worker = client_with_worker
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'Subtitle Pruner' in resp.data


class TestApiStatus:
    def test_status_returns_json(self, client_with_worker):
        client, worker = client_with_worker
        resp = client.get('/api/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'counts' in data
        assert 'worker_running' in data

    def test_status_reflects_queued_items(self, client_with_worker):
        client, worker = client_with_worker
        client.post('/webhook', json={'file_path': '/media/test.mkv'})
        resp = client.get('/api/status')
        data = resp.get_json()
        assert data['counts']['pending'] == 1


class TestClearHistory:
    def test_clear_empty_queue(self, client_with_worker):
        client, worker = client_with_worker
        resp = client.delete('/api/queue')
        assert resp.status_code == 200
        assert resp.get_json()['cleared'] == 0


class TestRetryEntry:
    def test_retry_nonexistent_returns_404(self, client_with_worker):
        client, worker = client_with_worker
        resp = client.post('/api/retry/nonexist')
        assert resp.status_code == 404

    def test_retry_failed_entry_returns_ok(self, client_with_worker):
        client, worker = client_with_worker
        # Queue a file, then mark it as failed
        resp = client.post('/webhook', json={'file_path': '/media/test.mkv'})
        entry_id = resp.get_json()['entry']['id']
        with worker.lock:
            worker.queue[0]['status'] = 'failed'
            worker.queue[0]['error'] = 'test error'
        # Retry it
        resp = client.post(f'/api/retry/{entry_id}')
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'ok'
