"""The static frontend: "/" and every asset are served, the modules link up, and the JavaScript parses.

The browser code itself is checked by hand (see the OpenSpec tasks 5.1-5.4). These tests catch broken
references, missing exports, syntax errors and innerHTML use, which is not allowed for server strings.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "web" / "static"
JS_FILES = sorted(STATIC.rglob("*.js"))
ASSETS = sorted(p.relative_to(STATIC).as_posix() for p in STATIC.rglob("*") if p.is_file() and p.name != "index.html")
IMPORT_RE = re.compile(r"import\s*\{([^}]*)\}\s*from\s*'(\.[^']+)'")
EXPORT_RE = re.compile(r"export\s+(?:async\s+)?(?:function|class|const|let)\s+(\w+)")


def test_index_is_the_app_shell(web_client):
    response = web_client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<main id="view"' in response.text
    assert 'src="/app.js"' in response.text
    assert 'href="/styles.css"' in response.text


@pytest.mark.parametrize("asset", ASSETS)
def test_each_asset_is_served_at_its_root_path(web_client, asset):
    response = web_client.get(f"/{asset}")
    assert response.status_code == 200
    assert response.content == (STATIC / asset).read_bytes()
    if asset.endswith(".js"):
        assert "javascript" in response.headers["content-type"]
    if asset.endswith(".css"):
        assert response.headers["content-type"].startswith("text/css")


def test_index_references_only_existing_files():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for ref in re.findall(r'(?:href|src)="/([^"]+)"', html):
        assert (STATIC / ref).is_file(), ref


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.relative_to(STATIC).as_posix())
def test_module_imports_resolve_to_exports(path):
    for names, spec in IMPORT_RE.findall(path.read_text(encoding="utf-8")):
        target = (path.parent / spec).resolve()
        assert target.is_file(), f"{path.name} imports missing module {spec}"
        exported = set(EXPORT_RE.findall(target.read_text(encoding="utf-8")))
        for name in (n.strip() for n in names.split(",") if n.strip()):
            assert name in exported, f"{path.name} imports {name} from {spec}, which does not export it"


def test_server_strings_never_reach_innerhtml():
    for path in JS_FILES:
        source = path.read_text(encoding="utf-8")
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML"):
            assert banned not in source, f"{path.name} uses {banned}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.relative_to(STATIC).as_posix())
def test_javascript_parses(path):
    result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
