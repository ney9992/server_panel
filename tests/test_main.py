import importlib
import os
from pathlib import Path

from fastapi.testclient import TestClient

os.environ['PANEL_PASSWORD'] = 'testpass'
os.environ['PANEL_SECRET'] = '0123456789abcdef0123456789abcdef'
os.environ['DATA_ROOT'] = '/tmp/server_panel_test_media'
main = importlib.import_module('app.main')


def test_auth_and_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'MEDIA', tmp_path / 'media')
    monkeypatch.setattr(main, 'DOWNLOADS', tmp_path / 'downloads')
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    with TestClient(main.app) as client:
        assert client.get('/api/state').status_code == 401
        assert client.post('/api/login', json={'user': 'admin', 'password': 'bad'}).status_code == 401
        assert client.post('/api/login', json={'user': 'admin', 'password': 'testpass'}).status_code == 200
        response = client.post('/api/upload?kind=movies&name=test.mkv', content=b'video', headers={'Content-Type':'application/octet-stream'})
        assert response.status_code == 200, response.text
        assert (tmp_path / 'media' / 'movies' / 'test.mkv').read_bytes() == b'video'
        response = client.post('/api/upload?kind=movies&name=..%2Fsecret.mkv', content=b'next')
        assert response.status_code == 200
        assert (tmp_path / 'media' / 'movies' / 'secret.mkv').exists()
        assert client.post('/api/upload?kind=movies&name=run.sh', content=b'evil').status_code == 400
        assert client.post('/api/torrents', json={'kind': 'movies', 'url': 'file:///etc/passwd'}).status_code == 400
        assert client.post('/api/upload?kind=movies&name=test.mkv', content=b'again').json()['file'] == 'test (1).mkv'
        assert client.get('/api/state').status_code == 200
        assert client.post('/api/logout').status_code == 200
        assert client.get('/api/state').status_code == 401


def test_filename_safety():
    assert main.safe_name('../../movie.mkv') == 'movie.mkv'
    assert main.safe_name('a\\b.mkv') == 'b.mkv'
    assert main.extension_allowed('track.FLAC','music')
    assert not main.extension_allowed('track.flac','movies')
