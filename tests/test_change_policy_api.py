from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api import changes
from backend.app.services.change_episodes import _anomaly_signal


def test_watch_list_filter_summary_and_detail(monkeypatch):
    signal = _anomaly_signal({'id': 123, 'anomaly_type': 'latency', 'severity': 'critical',
                              'target_service': 'test', 'detected_at': 1800000000000,
                              'current_value': 600, 'baseline_value': 100})
    monkeypatch.setattr(changes, '_load_signals', lambda *args: [signal])
    monkeypatch.setattr(changes, 'get_source_signals', lambda *args: [signal])
    def attach(episodes):
        for episode in episodes:
            episode['semantic_assessment'] = {'status': 'not_evaluated'}
    monkeypatch.setattr(changes, 'attach_semantic_assessments', attach)
    app = FastAPI()
    app.include_router(changes.router)
    with TestClient(app) as client:
        response = client.get('/api/v1/changes?state=watch')
        assert response.status_code == 200
        body = response.json()
        assert body['summary']['watch'] == 1
        assert body['summary']['needs_attention'] == 0
        assert body['items'][0]['previous_evaluation']['state'] == 'critical'
        detail = client.get('/api/v1/changes/anm-123')
        assert detail.status_code == 200
        assert detail.json()['state'] == 'watch'
        assert client.get('/api/v1/changes?state=critical').json()['items'] == []
