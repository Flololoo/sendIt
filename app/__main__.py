"""Start the local video workspace: python -m app [--no-browser]

Binds to 127.0.0.1 only, prints the address, and opens it in the default browser.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

import uvicorn

from app.web import create_app

HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}/"
BROWSER_DELAY = 1.0  # seconds, so the server is listening before the browser asks for it


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app", description="Run the send.it.slowly video workspace.")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args(argv)

    print(f"send.it.slowly workspace: {URL}  (Ctrl+C to stop)", flush=True)
    if not args.no_browser:
        threading.Timer(BROWSER_DELAY, webbrowser.open, args=(URL,)).start()
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
