"""Celina desktop - native Windows window over the local app.

Starts the in-process stdlib server on an ephemeral loopback port, then opens
a pywebview window pointed at it. Closing the window ends the process; the
server runs on a daemon thread and dies with it.

Run from source:  python server/desktop.py
Frozen exe:       Celina.exe   (built via celina.spec / build.ps1)
"""

import os
import sys
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app  # noqa: E402


class Api:
    """Exposed to the page as window.pywebview.api. Opens external links in the
    system browser so they never replace the app window."""

    def open_external(self, url):
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            webbrowser.open(url)
            return True
        return False


def start_server():
    """Bind an ephemeral loopback port and serve on a daemon thread.
    Returns (server, port)."""
    srv = app.make_server(port=0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def run():
    import webview  # imported here so tests can load this module GUI-free

    _srv, port = start_server()
    webview.create_window(
        "Celina",
        f"http://127.0.0.1:{port}",
        width=1280,
        height=820,
        min_size=(940, 600),
        background_color="#FFF8F6",
        js_api=Api(),
    )
    webview.start()


if __name__ == "__main__":
    run()
