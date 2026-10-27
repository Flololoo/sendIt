"""Task 1.1: the app shell. `python -m app` binds loopback, prints the URL and opens the browser.

GET / serves the static page.
"""

import importlib
import socket
import subprocess
import sys
from pathlib import Path

import pytest

app_main = importlib.import_module("app.__main__")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_real_workspace(monkeypatch, web_paths, web_registry):
    """main() builds the app; keep that workspace under tmp_path, never the real data/."""
    from app.web import create_app

    monkeypatch.setattr(app_main, "create_app", lambda: create_app(web_paths, registry=web_registry))


def test_index_is_served_at_root(web_client):
    response = web_client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "workspace" in response.text


def test_bind_host_is_loopback(monkeypatch):
    calls = {}
    monkeypatch.setattr(app_main.uvicorn, "run", lambda app, **kwargs: calls.update(kwargs))
    monkeypatch.setattr(app_main.webbrowser, "open", lambda url: None)
    assert app_main.main(["--no-browser"]) == 0
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8765


def test_startup_prints_the_url_and_opens_the_browser(monkeypatch, capsys):
    opened = []

    class ImmediateTimer:
        def __init__(self, delay, fn, args=()):
            self.fn, self.args = fn, args

        def start(self):
            self.fn(*self.args)

    monkeypatch.setattr(app_main.uvicorn, "run", lambda app, **kwargs: None)
    monkeypatch.setattr(app_main.threading, "Timer", ImmediateTimer)
    monkeypatch.setattr(app_main.webbrowser, "open", lambda url: opened.append(url))
    app_main.main([])
    assert "http://127.0.0.1:8765/" in capsys.readouterr().out
    assert opened == ["http://127.0.0.1:8765/"]


def test_no_browser_flag_keeps_the_browser_closed(monkeypatch):
    monkeypatch.setattr(app_main.uvicorn, "run", lambda app, **kwargs: None)
    monkeypatch.setattr(app_main.threading, "Timer", lambda *a, **k: pytest.fail("browser timer started"))
    assert app_main.main(["--no-browser"]) == 0


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


@pytest.mark.skipif(not _port_free(8765), reason="port 8765 is in use by another instance")
def test_python_m_app_prints_the_url(tmp_path):
    # Same entry point as `python -m app`, but the workspace lives under tmp_path instead of the real data/.
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "import app.__main__ as m\n"
        "from app.web import create_app\n"
        "from app.workspace import WorkspacePaths\n"
        f"root = Path({str(tmp_path)!r})\n"
        "paths = WorkspacePaths(data_dir=root / 'data', exports_dir=root / 'exports',\n"
        "                       videos_dir=root / 'videos', project_root=root)\n"
        "m.create_app = lambda: create_app(paths)\n"
        "sys.exit(m.main(['--no-browser']))\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        line = proc.stdout.readline()
        assert "http://127.0.0.1:8765/" in line
    finally:
        proc.terminate()
        proc.wait(timeout=30)
