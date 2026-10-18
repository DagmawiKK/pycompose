"""Real libraries used through the same public interface as external recipes."""

import sqlite3
import threading
from pathlib import Path

import httpx
import pytest

from pycompose.integrations.httpx import client
from pycompose.integrations.sqlite import database


def test_httpx_extension_returns_normal_responses_and_closes_its_client() -> None:
    threads: list[int] = []
    clients: list[httpx.Client] = []

    def reply(request: httpx.Request) -> httpx.Response:
        threads.append(threading.get_ident())
        return httpx.Response(200, json={"path": request.url.path, "label": "café"})

    resource = client(
        transport=httpx.MockTransport(reply), base_url="https://fixture.test"
    )

    def fetch(session: httpx.Client) -> httpx.Response:
        clients.append(session)
        return session.get("/page")

    response = resource.submit(fetch).result(timeout=3)
    assert response.json() == {"path": "/page", "label": "café"}
    assert isinstance(response, httpx.Response)
    resource.close().result(timeout=3)
    assert clients[0].is_closed
    assert threads[0] != threading.get_ident()


def test_sqlite_extension_uses_normal_transactions_and_survives_reopening(
    tmp_path: Path,
) -> None:
    filename = tmp_path / "cache.db"
    resource = database(filename)

    def write(connection: sqlite3.Connection) -> None:
        with connection:
            connection.execute("CREATE TABLE pages (id INTEGER PRIMARY KEY, body TEXT)")
            connection.execute("INSERT INTO pages VALUES (?, ?)", (1, "cached café"))

    resource.submit(write).result(timeout=3)
    resource.close().result(timeout=3)
    reopened = database(filename)
    try:
        assert (
            reopened.submit(
                lambda connection: connection.execute(
                    "SELECT body FROM pages"
                ).fetchone()[0]
            ).result(timeout=3)
            == "cached café"
        )

        def rollback(connection: sqlite3.Connection) -> None:
            with connection:
                connection.execute("INSERT INTO pages VALUES (?, ?)", (2, "partial"))
                raise ValueError("abort")

        with pytest.raises(ValueError, match="abort"):
            reopened.submit(rollback).result(timeout=3)
        assert (
            reopened.submit(
                lambda connection: connection.execute(
                    "SELECT COUNT(*) FROM pages"
                ).fetchone()[0]
            ).result(timeout=3)
            == 1
        )
    finally:
        reopened.close().result(timeout=3)


@pytest.mark.parametrize("timeout", [None, 0, -1, float("inf"), float("nan"), True])
def test_httpx_extension_requires_a_finite_positive_timeout(timeout: object) -> None:
    with pytest.raises(ValueError, match="timeout"):
        client(timeout=timeout)  # type: ignore[arg-type]
