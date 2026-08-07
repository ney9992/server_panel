"""Высокоуровневое API, которое экспонируется в pywebview (window.pywebview.api)."""
from __future__ import annotations

import uuid

from . import config as cfg_mod
from . import ssh_manager


class Api:
    """Методы этого класса доступны из JS как window.pywebview.api.<method>(...)."""

    def __init__(self):
        self._window = None

    def set_window(self, window):
        self._window = window

    # ---------- серверы ----------

    def list_servers(self):
        servers = cfg_mod.list_servers()
        # не отдаём пароли в UI
        return [{k: v for k, v in s.items() if k != "password"} for s in servers]

    def save_server(self, server: dict):
        if not server.get("id"):
            server["id"] = str(uuid.uuid4())[:8]
        server.setdefault("port", 22)
        server.setdefault("auth", "password")
        server.setdefault("projects_dir", "/mnt/data/projects")
        server.setdefault("flash_mount", "/mnt/data")

        # Валидация
        if not server.get("host") or not server.get("user"):
            raise ValueError("host и user обязательны")

        auth = server.get("auth")
        if auth == "password" and not server.get("password"):
            raise ValueError("Пароль обязателен при аутентификации по паролю")
        if auth == "key" and not server.get("key_path"):
            raise ValueError("Путь к ключу обязателен при аутентификации по ключу")

        if server.get("auth") == "password" and not server.get("password"):
            existing = cfg_mod.get_server(server["id"])
            if existing:
                server["password"] = existing.get("password", "")

        cfg_mod.upsert_server(server)
        return {"ok": True, "id": server["id"]}

    def delete_server(self, server_id: str):
        cfg_mod.delete_server(server_id)
        return {"ok": True}

    def test_connection(self, server_id: str):
        server = cfg_mod.get_server(server_id)
        if not server:
            return {"ok": False, "error": "сервер не найден"}
        return ssh_manager.test_connection(server)

    # ---------- метрики / дашборд ----------

    def get_metrics(self, server_id: str):
        server = cfg_mod.get_server(server_id)
        if not server:
            return {"ok": False, "error": "сервер не найден"}
        try:
            return ssh_manager.call_agent(server, {"action": "metrics"})
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def get_logs(self, server_id: str, name: str, lines: int = 200):
        server = cfg_mod.get_server(server_id)
        if not server:
            return {"ok": False, "error": "сервер не найден"}
        try:
            return ssh_manager.call_agent(server, {"action": "logs", "name": name, "lines": lines})
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    # ---------- деплой / удаление ----------

    def deploy_project(self, server_id: str, name: str, git_url: str, branch: str = "main",
                        type_: str = "", custom_cmd: str = ""):
        server = cfg_mod.get_server(server_id)
        if not server:
            return {"ok": False, "error": "сервер не найден"}
        try:
            ssh_manager.bootstrap(server)
            payload = {
                "action": "deploy",
                "name": name,
                "git_url": git_url,
                "branch": branch or "main",
            }
            if type_:
                payload["type"] = type_
            if custom_cmd:
                payload["custom_cmd"] = custom_cmd
            return ssh_manager.call_agent(server, payload, timeout=300)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def remove_project(self, server_id: str, name: str):
        server = cfg_mod.get_server(server_id)
        if not server:
            return {"ok": False, "error": "сервер не найден"}
        try:
            return ssh_manager.call_agent(server, {"action": "remove", "name": name}, timeout=60)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def service_action(self, server_id: str, name: str, action: str):
        if action not in ("start", "stop", "restart"):
            return {"ok": False, "error": "недопустимое действие"}
        server = cfg_mod.get_server(server_id)
        if not server:
            return {"ok": False, "error": "сервер не найден"}
        try:
            return ssh_manager.call_agent(server, {"action": action, "name": name}, timeout=60)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
