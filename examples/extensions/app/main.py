"""HTTPX and SQLite used directly, their blocking calls run off the loop."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any, Literal

import httpx
from m3 import Button, Column, Row, Text
from settings import BASE_URL, HTTP_OPTIONS

from pycompose.app import App, Destination, Intent, ViewModel, to_thread
from pycompose.state import AppState
from pycompose.storage import paths

Endpoint = Literal["/posts", "/comments", "/albums", "/photos", "/todos", "/users"]
ENDPOINTS: tuple[Endpoint, ...] = (
    "/posts",
    "/comments",
    "/albums",
    "/photos",
    "/todos",
    "/users",
)


class Container:
    """One HTTP client and one database connection for the session."""

    def __init__(self) -> None:
        self.http = httpx.Client(base_url=BASE_URL, timeout=10.0, **HTTP_OPTIONS)
        # Opened here, then used only on the session's storage thread, one call
        # at a time and in order, so SQLite's own thread check is not needed.
        self.cache = sqlite3.connect(
            paths().files / "pages.sqlite3", timeout=5.0, check_same_thread=False
        )

    def close(self) -> None:
        """Release both, as the session ends."""
        self.http.close()
        self.cache.close()


class Pages(AppState):
    """Only the small current-page state is saved; cached pages live in SQLite."""

    page: int = 0
    endpoint: str = "/posts"
    preview: str = "No page loaded"
    status: str = "Ready"
    taps: int = 0


class ChooseEndpoint(Intent):
    endpoint: Endpoint


class Refresh(Intent):
    pass


class NextPage(Intent):
    pass


class LoadCache(Intent):
    pass


class Tap(Intent):
    pass


def _schema(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > 2:
        raise ValueError("cache uses a newer schema")
    with connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS resource_pages "
            "(endpoint TEXT NOT NULL, page INTEGER NOT NULL, body TEXT NOT NULL, "
            "PRIMARY KEY (endpoint, page))"
        )
        if version == 1:
            connection.execute(
                "INSERT OR IGNORE INTO resource_pages "
                "SELECT '/posts', page, body FROM pages"
            )
        connection.execute("PRAGMA user_version = 2")


def _rows(body: str, endpoint: str) -> list[dict[str, Any]]:
    rows = json.loads(body)
    label = "name" if endpoint in {"/comments", "/users"} else "title"
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or not isinstance(row.get(label), str) for row in rows
    ):
        raise ValueError("invalid page")
    return rows


def _save(connection: sqlite3.Connection, body: str, page: int, endpoint: str) -> None:
    # Reject malformed application data before replacing a known-good page.
    _rows(body, endpoint)
    _schema(connection)
    with connection:
        connection.execute(
            "INSERT OR REPLACE INTO resource_pages VALUES (?, ?, ?)",
            (endpoint, page, body),
        )


def _load(connection: sqlite3.Connection, page: int, endpoint: str) -> str:
    _schema(connection)
    row = connection.execute(
        "SELECT body FROM resource_pages WHERE endpoint = ? AND page = ?",
        (endpoint, page),
    ).fetchone()
    return row[0] if row else "[]"


def _get(http: httpx.Client, endpoint: str, page: int) -> httpx.Response:
    response = http.get(endpoint, params={"_start": page * 3, "_limit": 3})
    response.raise_for_status()
    return response


class PagesViewModel(ViewModel[Pages]):
    """Fetches, caches and shows one page at a time.

    A new request cancels the one before it, so a slow response can never
    overwrite the page the user asked for after it.

    Args:
        container: The session's client and database.
    """

    def __init__(self, container: Container) -> None:
        super().__init__(Pages())
        self._http = container.http
        self._cache = container.cache
        self._job: asyncio.Task[None] | None = None

    def on_intent(self, intent: Intent) -> None:
        match intent:
            case ChooseEndpoint(endpoint=endpoint):
                self._cancel()
                self.state = Pages(endpoint=endpoint, taps=self.state.taps)
            case Refresh():
                self._start(self._fetch(0), "Loading")
            case NextPage():
                self._start(self._fetch(self.state.page + 1), "Loading")
            case LoadCache():
                self._start(self._read(self.state.page), "Reading cache")
            case Tap():
                self.state = self.state.evolve(taps=self.state.taps + 1)

    def _cancel(self) -> None:
        if self._job is not None:
            self._job.cancel()

    def _start(self, work: Any, status: str) -> None:
        self._cancel()
        self.state = self.state.evolve(status=status)
        self._job = self.launch(work)

    async def _sql(self, work: Any, *args: object) -> Any:
        return await to_thread("storage", work, self._cache, *args)

    async def _fetch(self, page: int) -> None:
        endpoint = self.state.endpoint
        try:
            response = await to_thread("io", _get, self._http, endpoint, page)
            await self._sql(_save, response.text, page, endpoint)
        except (httpx.HTTPError, sqlite3.Error, ValueError) as exc:
            self.state = self.state.evolve(
                status=f"Retry available: {type(exc).__name__}"
            )
            return
        origin = f"HTTP {response.status_code}; SQLite saved"
        self._show(response.text, page, endpoint, origin)

    async def _read(self, page: int) -> None:
        endpoint = self.state.endpoint
        try:
            body = await self._sql(_load, page, endpoint)
            self._show(body, page, endpoint, "SQLite cache")
        except (sqlite3.Error, ValueError) as exc:
            self.state = self.state.evolve(
                status=f"Retry available: {type(exc).__name__}"
            )

    def _show(self, body: str, page: int, endpoint: str, origin: str) -> None:
        rows = _rows(body, endpoint)
        label = "name" if endpoint in {"/comments", "/users"} else "title"
        self.state = self.state.evolve(
            page=page,
            preview="\n".join(row[label][:100] for row in rows) or "No cached items",
            status=f"{origin}: {len(rows)} items",
        )


def screen(state: Pages) -> Column:
    return Column(
        id="screen",
        children=[
            Text(id="heading", text="Extension proof"),
            *[
                Row(
                    id=f"endpoints_{index}",
                    children=[
                        Button(
                            id=f"select_{endpoint[1:]}",
                            text=endpoint,
                            on_click=ChooseEndpoint(endpoint=endpoint),
                        )
                        for endpoint in ENDPOINTS[index : index + 3]
                    ],
                )
                for index in (0, 3)
            ],
            Text(id="status", text=state.status),
            Text(id="page", text=f"{state.endpoint} • Page {state.page + 1}"),
            Text(id="preview", text=state.preview),
            Button(id="refresh", on_click=Refresh(), text="Refresh"),
            Button(id="next", on_click=NextPage(), text="Next page"),
            Button(id="cache", on_click=LoadCache(), text="Load cache"),
            Button(id="tap", on_click=Tap(), text=f"Tap UI: {state.taps}"),
        ],
    )


app = App(
    start=Destination(lambda container, _route: PagesViewModel(container), screen),
    container=Container,
)
