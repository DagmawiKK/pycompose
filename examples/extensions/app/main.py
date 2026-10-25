"""Direct HTTPX and SQLite operations, both supplied as optional extensions."""

import json
import sqlite3
from types import SimpleNamespace
from typing import Any, Literal, TypedDict

from m3 import Button, Column, Row, Text
from settings import BASE_URL, HTTP_OPTIONS

from pycompose.errors import StateError
from pycompose.extensions import paths
from pycompose.integrations.httpx import client
from pycompose.integrations.sqlite import database
from pycompose.state import App, AppState, Registry

actions = Registry()
ENDPOINTS = ("/posts", "/comments", "/albums", "/photos", "/todos", "/users")


class Session(AppState):
    """Only the small current-page shell is saved; cached pages live in SQLite."""

    page: int = 0
    endpoint: str = "/posts"
    request_id: int = 0
    preview: str = "No page loaded"
    status: str = "Ready"
    taps: int = 0


class Page(TypedDict):
    body: str
    page: int
    request_id: int
    endpoint: str
    http_status: int


def container() -> SimpleNamespace:
    return SimpleNamespace(
        http=client(base_url=BASE_URL, **HTTP_OPTIONS),
        cache=database(paths().files / "pages.sqlite3"),
    )


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


def _save(connection: sqlite3.Connection, body: str, page: int, endpoint: str) -> str:
    # Reject malformed application data before replacing a known-good page.
    _rows(body, endpoint)
    _schema(connection)
    with connection:
        connection.execute(
            "INSERT OR REPLACE INTO resource_pages VALUES (?, ?, ?)",
            (endpoint, page, body),
        )
    return body


def _load(connection: sqlite3.Connection, page: int, endpoint: str) -> str:
    _schema(connection)
    row = connection.execute(
        "SELECT body FROM resource_pages WHERE endpoint = ? AND page = ?",
        (endpoint, page),
    ).fetchone()
    return row[0] if row else "[]"


@actions
def failed(session: Session, error: str, request_id: int) -> Session:
    if request_id != session.request_id:
        return session
    return session.evolve(status=f"Retry available: {error}")


@actions
def cached(
    session: Session,
    body: str,
    page: int,
    request_id: int,
    endpoint: str,
    http_status: int,
) -> Session:
    if request_id != session.request_id:
        return session
    rows = _rows(body, endpoint)
    label = "name" if endpoint in {"/comments", "/users"} else "title"
    origin = f"HTTP {http_status}; SQLite saved" if http_status else "SQLite cache"
    return session.evolve(
        page=page,
        preview="\n".join(row[label][:100] for row in rows) or "No cached items",
        status=f"{origin}: {len(rows)} items",
    )


@actions
def received(
    session: Session,
    body: str,
    page: int,
    request_id: int,
    endpoint: str,
    http_status: int,
    *,
    cache: Any,
) -> Session:
    if request_id != session.request_id:
        return session
    try:
        cache.submit(
            lambda connection: _save(connection, body, page, endpoint),
            success=cached,
            failure=failed,
            encode=lambda saved: {
                "body": saved,
                "page": page,
                "request_id": request_id,
                "endpoint": endpoint,
                "http_status": http_status,
            },
            error=lambda exc: {
                "error": type(exc).__name__,
                "request_id": request_id,
            },
            key="page",
            policy="latest",
        )
    except StateError:
        return session.evolve(status="Cache busy; retry available")
    return session.evolve(status="Saving cache")


def _fetch(session: Session, page: int, http: Any) -> Session:
    generation = session.request_id + 1

    def fetch(http: Any) -> Any:
        response = http.get(session.endpoint, params={"_start": page * 3, "_limit": 3})
        response.raise_for_status()
        return response

    try:
        http.submit(
            fetch,
            success=received,
            failure=failed,
            encode=lambda response: {
                "body": response.text,
                "page": page,
                "request_id": generation,
                "endpoint": session.endpoint,
                "http_status": response.status_code,
            },
            error=lambda exc: {"error": type(exc).__name__, "request_id": generation},
            key="page",
            policy="latest",
        )
    except StateError:
        return session.evolve(
            request_id=generation, status="Network busy; retry available"
        )
    return session.evolve(request_id=generation, status="Loading")


@actions
def choose_endpoint(
    session: Session,
    endpoint: Literal["/posts", "/comments", "/albums", "/photos", "/todos", "/users"],
) -> Session:
    return session.evolve(
        endpoint=endpoint,
        page=0,
        request_id=session.request_id + 1,
        preview="No page loaded",
        status="Ready",
    )


@actions
def refresh(session: Session, *, http: Any) -> Session:
    return _fetch(session, 0, http)


@actions
def next_page(session: Session, *, http: Any) -> Session:
    return _fetch(session, session.page + 1, http)


@actions
def load_cache(session: Session, *, cache: Any) -> Session:
    generation = session.request_id + 1
    try:
        cache.submit(
            lambda connection: _load(connection, session.page, session.endpoint),
            success=cached,
            failure=failed,
            encode=lambda body: {
                "body": body,
                "page": session.page,
                "request_id": generation,
                "endpoint": session.endpoint,
                "http_status": 0,
            },
            error=lambda exc: {"error": type(exc).__name__, "request_id": generation},
            key="page",
            policy="latest",
        )
    except StateError:
        return session.evolve(
            request_id=generation, status="Cache busy; retry available"
        )
    return session.evolve(request_id=generation, status="Reading cache")


@actions
def tap(session: Session) -> Session:
    return session.evolve(taps=session.taps + 1)


def view(session: Session) -> Column:
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
                            on_click=actions.choose_endpoint.with_args(
                                endpoint=endpoint,
                            ),
                        )
                        for endpoint in ENDPOINTS[index : index + 3]
                    ],
                )
                for index in (0, 3)
            ],
            Text(id="status", text=session.status),
            Text(id="page", text=f"{session.endpoint} • Page {session.page + 1}"),
            Text(id="preview", text=session.preview),
            Button(
                id="refresh",
                on_click=actions.refresh.binding(),
                text="Refresh",
            ),
            Button(
                id="next",
                on_click=actions.next_page.binding(),
                text="Next page",
            ),
            Button(
                id="cache",
                on_click=actions.load_cache.binding(),
                text="Load cache",
            ),
            Button(
                id="tap",
                on_click=actions.tap.binding(),
                text=f"Tap UI: {session.taps}",
            ),
        ],
    )


app = App(state=Session, view=view, container=container)
