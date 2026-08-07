"""Подключение по SSH к серверу и вызов агента srvman-agent.sh по JSON-протоколу."""
import json
import posixpath
import time
from pathlib import Path

import paramiko

AGENT_LOCAL_PATH = Path(__file__).resolve().parent.parent / "agent" / "srvman-agent.sh"
AGENT_REMOTE_PATH = "/usr/local/bin/srvman-agent.sh"


class AgentError(Exception):
    pass


def _connect(server: dict) -> paramiko.SSHClient:
    """Подключение по SSH с защитой от пустого пароля и ключа."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Определяем аутентификацию
    auth = server.get("auth", "password")
    password = server.get("password", "")
    key_path = server.get("key_path", "")

    if auth == "key" and key_path:
        if not Path(key_path).exists():
            raise ValueError(f"Ключевой файл не найден: {key_path}")
        kwargs = {
            "hostname": server["host"],
            "port": int(server.get("port", 22)),
            "username": server["user"],
            "key_filename": key_path,
            "timeout": 30,
            "banner_timeout": 30,
            "auth_timeout": 30,
        }
    elif password:
        kwargs = {
            "hostname": server["host"],
            "port": int(server.get("port", 22)),
            "username": server["user"],
            "password": password,
            "allow_agent": False,
            "look_for_keys": False,
            "timeout": 30,
            "banner_timeout": 30,
            "auth_timeout": 30,
        }
    else:
        raise ValueError("Не указан ни пароль, ни путь к ключу")

    for attempt in range(3):  # 3 попытки с backoff
        try:
            client.connect(**kwargs)
            return client
        except paramiko.AuthenticationException:
            raise
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)  # простая backoff
            continue
    raise ValueError("Не удалось подключиться по SSH")


def bootstrap(server: dict) -> None:
    """Загружает агент на сервер (при первом подключении / после обновления скрипта)."""
    client = _connect(server)
    try:
        sftp = client.open_sftp()
        try:
            sftp.mkdir(posixpath.dirname(AGENT_REMOTE_PATH))
        except IOError:
            pass
        sftp.put(str(AGENT_LOCAL_PATH), AGENT_REMOTE_PATH)
        sftp.chmod(AGENT_REMOTE_PATH, 0o755)
        sftp.close()

        projects_dir = server.get("projects_dir", "/mnt/data/projects")
        flash_mount = server.get("flash_mount", "/mnt/data")
        cmd = (
            f"mkdir -p '{projects_dir}' && "
            f"(command -v bash >/dev/null 2>&1 || (apk update >/dev/null 2>&1; apk add --no-cache bash jq git >/dev/null 2>&1))"
        )
        _, stdout, stderr = client.exec_command(cmd, timeout=120)
        stdout.channel.recv_exit_status()
    finally:
        client.close()


def call_agent(server: dict, payload: dict, timeout: int = 120) -> dict:
    """Выполняет одну команду агента: пишет JSON в stdin, читает JSON из stdout."""
    client = _connect(server)
    try:
        env_prefix = (
            f"SRVMAN_PROJECTS_DIR='{server.get('projects_dir', '/mnt/data/projects')}' "
            f"SRVMAN_FLASH_MOUNT='{server.get('flash_mount', '/mnt/data')}' "
        )
        command = f"{env_prefix}bash {AGENT_REMOTE_PATH}"
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        stdin.write(json.dumps(payload, ensure_ascii=False))
        stdin.channel.shutdown_write()

        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()

        if not out.strip():
            raise AgentError(f"пустой ответ агента (exit={exit_code}): {err.strip() or 'нет данных'}")

        try:
            return json.loads(out.strip().splitlines()[-1])
        except json.JSONDecodeError as e:
            raise AgentError(f"не удалось разобрать ответ агента: {e}; вывод: {out[:500]}")
    finally:
        client.close()


def test_connection(server: dict) -> dict:
    try:
        bootstrap(server)
        result = call_agent(server, {"action": "ping"}, timeout=20)
        return {"ok": bool(result.get("ok")), "detail": result}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
