from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse

import pytest

from .support import LiveChrome, start_chrome, terminate_process_group


class LocalSite:
    def __init__(self, server: ThreadingHTTPServer, thread: threading.Thread) -> None:
        self.server = server
        self.thread = thread

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def url(self, path: str) -> str:
        return f"{self.origin}{path}"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/slow":
            import time

            time.sleep(float(query.get("delay", ["2"])[0]))
        token = query.get("token", ["default"])[0]
        title = query.get("title", ["Browser Automation Integration"])[0]
        if parsed.path == "/next":
            body = f"""<!doctype html><html><head><title>{title}</title></head>
<body><h1 id="heading">Next Page {token}</h1><a id="back" href="/page">Back</a></body></html>"""
        else:
            body = f"""<!doctype html><html><head><title>{title}</title>
<style>.hidden {{ display:none }}</style></head><body data-token="{token}">
<h1 id="heading">Integration Page {token}</h1>
<label for="name">Name</label><input id="name" placeholder="Name">
<button id="go" type="button" onclick="document.querySelector('#status').textContent='clicked:'+document.querySelector('#name').value">Go</button>
<p id="status">idle</p><a id="next" href="/next?token={token}">Next</a>
<script>window.fixtureLoaded = true;</script></body></html>"""
        payload = body.encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("BROWSER_AUTOMATION_REAL_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="set BROWSER_AUTOMATION_REAL_TESTS=1 to run executable integration coverage")
    for item in items:
        if item.get_closest_marker("real_chrome") is not None:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def test_site() -> LocalSite:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, name="browser-automation-test-site", daemon=True)
    thread.start()
    site = LocalSite(server, thread)
    yield site
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def live_chrome(tmp_path_factory: pytest.TempPathFactory) -> LiveChrome:
    root = tmp_path_factory.mktemp("browser-automation-real")
    chrome = start_chrome(root)
    yield chrome
    terminate_process_group(chrome.process)


@pytest.fixture
def live_environment(live_chrome: LiveChrome, tmp_path: Path) -> dict[str, str]:
    return live_chrome.environment(tmp_path)
