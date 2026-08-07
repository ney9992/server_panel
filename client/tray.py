"""Иконка в трее (pystray): сводный статус серверов, быстрые действия, открытие окна."""
from __future__ import annotations

import threading
import time

import pystray
from PIL import Image, ImageDraw

from . import config as cfg_mod
from . import ssh_manager

POLL_INTERVAL_SEC = 60

COLOR_OK = (62, 207, 110)
COLOR_ERR = (229, 72, 77)
COLOR_UNKNOWN = (154, 155, 160)
COLOR_NONE = (100, 100, 100)


def _make_icon_image(color) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, size - 4, size - 4), fill=(45, 45, 48, 255))
    d.ellipse((18, 18, size - 18, size - 18), fill=color + (255,))
    return img


class TrayApp:
    def __init__(self, show_window_cb, quit_cb):
        self._show_window_cb = show_window_cb
        self._quit_cb = quit_cb
        self._status = {}  # server_id -> bool|None
        self._icon = pystray.Icon("srvman", _make_icon_image(COLOR_NONE), "SrvMan", self._build_menu())
        self._stop_flag = threading.Event()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)

    def _build_menu(self):
        servers = cfg_mod.list_servers()
        items = [
            pystray.MenuItem("Открыть панель", self._on_open, default=True),
            pystray.Menu.SEPARATOR,
        ]
        if servers:
            for s in servers:
                st = self._status.get(s["id"])
                label = f"{s.get('name', s.get('host'))} — {self._status_label(st)}"
                items.append(pystray.MenuItem(label, self._on_open, enabled=False))
            items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Обновить статус", self._on_refresh_now))
        items.append(pystray.MenuItem("Выход", self._on_quit))
        return pystray.Menu(*items)

    @staticmethod
    def _status_label(st):
        if st is True:
            return "в норме"
        if st is False:
            return "недоступен"
        return "неизвестно"

    def _on_open(self, icon=None, item=None):
        self._show_window_cb()

    def _on_refresh_now(self, icon=None, item=None):
        threading.Thread(target=self._poll_once, daemon=True).start()

    def _on_quit(self, icon=None, item=None):
        self._stop_flag.set()
        self._icon.stop()
        self._quit_cb()

    def _poll_once(self):
        servers = cfg_mod.list_servers()
        for s in servers:
            try:
                res = ssh_manager.call_agent(s, {"action": "ping"}, timeout=10)
                self._status[s["id"]] = bool(res.get("ok"))
            except Exception:  # noqa: BLE001
                self._status[s["id"]] = False

        if not servers:
            color = COLOR_NONE
        elif all(v is True for v in self._status.values()):
            color = COLOR_OK
        elif all(v is False for v in self._status.values()):
            color = COLOR_ERR
        else:
            color = COLOR_UNKNOWN

        self._icon.icon = _make_icon_image(color)
        self._icon.menu = self._build_menu()

    def _poll_loop(self):
        while not self._stop_flag.is_set():
            self._poll_once()
            self._stop_flag.wait(POLL_INTERVAL_SEC)

    def run(self):
        self._poll_thread.start()
        self._icon.run()

    def stop(self):
        self._stop_flag.set()
        self._icon.stop()
