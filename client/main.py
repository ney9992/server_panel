"""Точка входа SrvMan: окно pywebview + иконка в трее."""
from __future__ import annotations

import os
import sys
import threading

import webview

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from client.api import Api
    from client.tray import TrayApp
else:
    from .api import Api
    from .tray import TrayApp

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")


def main():
    api = Api()
    window = webview.create_window(
        "SrvMan",
        url=os.path.join(UI_DIR, "index.html"),
        js_api=api,
        width=1100,
        height=720,
        hidden=True,
    )
    api.set_window(window)

    def on_closing():
        window.hide()
        return False  # отменяем реальное закрытие/уничтожение окна

    window.events.closing += on_closing

    def show_window():
        window.show()

    def quit_app():
        window.destroy()
        os._exit(0)

    tray = TrayApp(show_window_cb=show_window, quit_cb=quit_app)
    tray_thread = threading.Thread(target=tray.run, daemon=True)
    tray_thread.start()

    # Окно стартует скрытым — приложение живёт в трее, окно открывается по клику на иконку.
    webview.start(debug=False)


if __name__ == "__main__":
    main()
