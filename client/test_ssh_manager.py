"""Тесты для ssh_manager.py."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from client.ssh_manager import _connect, test_connection, AgentError

# Mock config для тестов
@pytest.fixture
def mock_server():
    return {
        "host": "127.0.0.1",
        "port": 22,
        "user": "test",
        "auth": "password",
        "password": "testpass",
        "key_path": "",
        "projects_dir": "/tmp",
        "flash_mount": "/tmp"
    }

def test_connect_password_success(mock_server):
    with patch("paramiko.SSHClient.connect") as mock_connect:
        client = _connect(mock_server)
        assert client is not None
        mock_connect.assert_called_once()

def test_connect_key_success():
    server = {
        "host": "127.0.0.1",
        "port": 22,
        "user": "test",
        "auth": "key",
        "password": "",
        "key_path": "/tmp/test.key",
        "projects_dir": "/tmp",
        "flash_mount": "/tmp"
    }
    with patch("paramiko.SSHClient.connect") as mock_connect:
        with patch("Path.exists", return_value=True):
            client = _connect(server)
            assert client is not None

def test_connect_validation_error():
    server = {
        "host": "127.0.0.1",
        "port": 22,
        "user": "test",
        "auth": "password",
        "password": "",  # пустой пароль
        "key_path": "",
        "projects_dir": "/tmp",
        "flash_mount": "/tmp"
    }
    with pytest.raises(ValueError):
        _connect(server)

def test_test_connection_success():
    with patch("client.ssh_manager._connect") as mock_connect, \
         patch("client.ssh_manager.call_agent") as mock_call:
        mock_call.return_value = {"ok": True}
        result = test_connection({"host": "127.0.0.1", "user": "test", "auth": "password", "password": "pass"})
        assert result["ok"] is True
