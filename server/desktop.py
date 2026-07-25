"""Reveriebot desktop - native Windows window over the local app.

Starts the in-process stdlib server on an ephemeral loopback port, then opens
a pywebview window pointed at it. Closing the window ends the process; the
server runs on a daemon thread and dies with it.

Run from source:  python server/desktop.py
Frozen exe:       Reveriebot.exe   (built via reveriebot.spec / build.ps1)
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app  # noqa: E402


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
        "Reveriebot",
        f"http://127.0.0.1:{port}",
        width=1280,
        height=820,
        min_size=(940, 600),
        background_color="#0B0F19",
    )
    webview.start()


if __name__ == "__main__":
    run()
