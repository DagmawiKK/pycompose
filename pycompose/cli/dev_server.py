"""Authenticated loopback development bundles and single-worker preview builds.

The debug host must pull source/resource bytes and reload Python on its worker.
The desktop snapshot is diagnostic evidence, not a replacement for host State.
Drawables/fonts require rebuilding; strings/assets are runtime-reload candidates.
"""

from __future__ import annotations

import base64
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import TracebackType
from typing import Self

from pycompose.cli.build import codegen
from pycompose.cli.project import (
    Project,
    ProjectError,
    check_project_versions,
    project_path,
)
from pycompose.cli.reload import AppReloader
from pycompose.cli.resources import resource_files

SESSION_LOCK = threading.Lock()


class DevServer:
    """A debug-only, authenticated full-bundle endpoint bound to loopback."""

    def __init__(self, project: Project, *, port: int = 0) -> None:
        """Configure a server without importing user code or binding a socket.

        Args:
            project: Project to watch and preview.
            port: Loopback port; zero selects a free ephemeral port.

        Raises:
            ProjectError: If the port or project versions are invalid.
        """
        if not 0 <= port <= 65535:
            raise ProjectError("dev server port must be between 0 and 65535")
        self._project = project
        self._schema = check_project_versions(project)
        self._port = port
        self.token = secrets.token_urlsafe(32)
        self.url = ""
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._http: HTTPServer | None = None
        self._body = b"{}"
        self._seen: dict[str, bytes] | None = None
        self._snapshot: str | None = None
        self._revision = 0
        self._startup_error: Exception | None = None
        self._owns_lock = False
        self._published: dict[str, bytes] = {}
        self._requires_rebuild = False

    def _files(self, app: AppReloader) -> dict[str, bytes]:
        configured = self._project.table("resources").get("path", "resources")
        if not isinstance(configured, str):
            raise ProjectError("resources.path must be a string")
        resources = project_path(self._project.root, configured)
        candidates = [*app.directory.rglob("*.py"), *resources.rglob("*")]
        output = {}
        for path in sorted(candidates):
            name = path.relative_to(self._project.root).as_posix()
            project_path(self._project.root, name)
            if path.is_file() and path.name not in {".gitkeep", ".DS_Store"}:
                output[name] = path.read_bytes()
        return output

    def _refresh(self, app: AppReloader) -> None:
        started = time.perf_counter()
        try:
            current = self._files(app)
            if current == self._seen:
                return
            # The app's generated package follows its source, so a component
            # used for the first time imports without a Gradle build.
            codegen(self._project, kotlin=False)
            current = self._files(app)
            previous = self._seen or {}
            self._seen = current
            resource_files(self._project)
            snapshot = app.snapshot()
            if self._files(app) != current:
                raise ProjectError("project changed during the preview build; retrying")
            self._snapshot = snapshot
            self._published = current
            self._revision += 1
            changed = current.keys() | previous.keys()
            rebuild = bool(previous) and any(
                "drawables" in name.split("/") or "fonts" in name.split("/")
                for name in changed
                if current.get(name) != previous.get(name)
            )
            self._requires_rebuild |= rebuild
            self._body = self._encode(current, started, None, self._requires_rebuild)
        except Exception as exc:
            self._body = self._encode(
                self._published,
                started,
                f"{type(exc).__name__}: {exc}",
                self._requires_rebuild,
            )

    def _encode(
        self, files: dict[str, bytes], started: float, error: str | None, rebuild: bool
    ) -> bytes:
        count = 0
        if self._snapshot:
            pending = [json.loads(self._snapshot)["root"]]
            while pending:
                node = pending.pop()
                count += 1
                pending.extend(node.get("children", []))
        return json.dumps(
            {
                "revision": self._revision,
                "schemaVersion": self._schema,
                "snapshot": self._snapshot,
                "files": {
                    name: base64.b64encode(value).decode("ascii")
                    for name, value in files.items()
                },
                "requiresRebuild": rebuild,
                "diagnostics": {
                    "nodeCount": count,
                    "buildMs": (time.perf_counter() - started) * 1000,
                    "lastError": error,
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self) -> None:
                super().setup()
                self.connection.settimeout(1)

            def do_GET(self) -> None:  # noqa: N802
                supplied = self.headers.get("Authorization", "")
                if not secrets.compare_digest(
                    supplied.encode(), f"Bearer {server.token}".encode()
                ):
                    self.send_error(401)
                    return
                if self.path != "/session":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(server._body)))
                self.end_headers()
                self.wfile.write(server._body)

            def log_message(self, _format: str, *args: object) -> None:
                pass

        return Handler

    def _work(self) -> None:
        app = None
        try:
            app = AppReloader(self._project, self._schema)
            self._refresh(app)
            self._ready.set()
            assert self._http is not None
            while not self._stop.is_set():
                self._refresh(app)
                self._http.handle_request()
        except Exception as exc:
            self._startup_error = exc
            self._ready.set()
        finally:
            if app is not None:
                app.close()

    def __enter__(self) -> Self:
        if not SESSION_LOCK.acquire(blocking=False):
            raise ProjectError("only one desktop reload session may run in a process")
        self._owns_lock = True
        try:
            self._http = HTTPServer(("127.0.0.1", self._port), self._handler())
            self._http.timeout = 0.05
            self.url = f"http://127.0.0.1:{self._http.server_port}"
            self._thread = threading.Thread(
                target=self._work, name="pycompose-dev", daemon=True
            )
            self._thread.start()
            self._ready.wait()
            if self._startup_error:
                raise self._startup_error
        except BaseException:
            self.close()
            raise
        return self

    def close(self) -> None:
        """Stop the worker and release the listening port and user imports."""
        self._stop.set()
        if self._thread:
            self._thread.join()
        if self._http:
            self._http.server_close()
        if self._owns_lock:
            self._http = None
            self._thread = None
            self._owns_lock = False
            SESSION_LOCK.release()

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()
