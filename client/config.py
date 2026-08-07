"""Загрузка и сохранение списка серверов (config.local.json в корне проекта)."""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.local.json"
EXAMPLE_PATH = ROOT / "config.example.json"


def _ensure_config() -> None:
    if not CONFIG_PATH.exists():
        if EXAMPLE_PATH.exists():
            shutil.copy(EXAMPLE_PATH, CONFIG_PATH)
        else:
            CONFIG_PATH.write_text(json.dumps({"servers": []}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config() -> dict:
    _ensure_config()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def list_servers() -> list:
    return load_config().get("servers", [])


def get_server(server_id: str) -> dict | None:
    for s in list_servers():
        if s.get("id") == server_id:
            return s
    return None


def upsert_server(server: dict) -> None:
    cfg = load_config()
    servers = cfg.setdefault("servers", [])
    for i, s in enumerate(servers):
        if s.get("id") == server["id"]:
            servers[i] = server
            save_config(cfg)
            return
    servers.append(server)
    save_config(cfg)


def delete_server(server_id: str) -> None:
    cfg = load_config()
    cfg["servers"] = [s for s in cfg.get("servers", []) if s.get("id") != server_id]
    save_config(cfg)
