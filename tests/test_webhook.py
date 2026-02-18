"""Tests for the /webhook endpoint — payload parsing and response codes."""


class TestWebhookTestEvent:
    def test_radarr_test_event_returns_200(self, client_with_worker):
        client, worker = client_with_worker
        resp = client.post('/webhook', json={
            'eventType': 'Test',
            'instanceName': 'Radarr'
        })
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'ok'

    def test_sonarr_test_event_returns_200(self, client_with_worker):
        client, worker = client_with_worker
        resp = client.post('/webhook', json={
            'eventType': 'Test',
            'instanceName': 'Sonarr'
        })
        assert resp.status_code == 200


class TestWebhookPayloadFormats:
    def test_simple_format_mkv(self, client_with_worker):
        client, worker = client_with_worker
        resp = client.post('/webhook', json={
            'file_path': '/media/movies/Test.mkv'
        })
        assert resp.status_code == 202
        assert resp.get_json()['status'] == 'queued'

    def test_radarr_format(self, client_with_worker):
        client, worker = client_with_worker
        resp = client.post('/webhook', json={
            'eventType': 'Download',
            'movieFile': {'path': '/media/movies/Film.mkv'}
        })
        assert resp.status_code == 202

    def test_radarr_relative_path(self, client_with_worker):
        client, worker = client_with_worker
        resp = client.post('/webhook', json={
            'eventType': 'Download',
            'movieFile': {'relativePath': 'Film.mkv'}
        })
        assert resp.status_code == 202

    def test_sonarr_format(self, client_with_worker):
        client, worker = client_with_worker
        resp = client.post('/webhook', json={
            'eventType': 'Download',
            'episodeFile': {'path': '/media/tv/Show/S01E01.mkv'}
        })
        assert resp.status_code == 202

    def test_nested_radarr_format(self, client_with_worker):
        client, worker = client_with_worker
        resp = client.post('/webhook', json={
            'movie': {'movieFile': {'path': '/media/movies/Film.mkv'}}
        })
        assert resp.status_code == 202

    def test_sonarr_episodes_array_format(self, client_with_worker):
        client, worker = client_with_worker
        resp = client.post('/webhook', json={
            'episodes': [
                {'episodeFile': {'path': '/media/tv/Show/S01E01.mkv'}}
            ]
        })
        assert resp.status_code == 202


class TestWebhookValidation:
    def test_non_mkv_ignored(self, client_with_worker):
        client, worker = client_with_worker
        resp = client.post('/webhook', json={
            'file_path': '/media/movies/Test.mp4'
        })
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'ignored'

    def test_empty_payload_returns_400(self, client_with_worker):
        client, worker = client_with_worker
        resp = client.post('/webhook', json={})
        assert resp.status_code == 400

    def test_duplicate_file_returns_existing_entry(self, client_with_worker):
        client, worker = client_with_worker
        resp1 = client.post('/webhook', json={'file_path': '/media/movies/Dup.mkv'})
        resp2 = client.post('/webhook', json={'file_path': '/media/movies/Dup.mkv'})
        assert resp1.status_code == 202
        assert resp2.status_code == 202
        assert resp1.get_json()['entry']['id'] == resp2.get_json()['entry']['id']

    def test_malformed_body_returns_400(self, client_with_worker):
        client, worker = client_with_worker
        resp = client.post('/webhook', data='not json',
                           content_type='application/json')
        assert resp.status_code == 400
