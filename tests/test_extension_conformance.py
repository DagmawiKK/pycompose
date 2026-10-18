"""Reference and third-party recipes share the shipped contributor conformance."""

import importlib
import sqlite3
import sys
from pathlib import Path
from typing import ClassVar

import httpx
import pytest

from pycompose.extensions import Resource
from pycompose.integrations.httpx import client
from pycompose.integrations.sqlite import database
from pycompose.testing.extension_contract import ResourceContract


class TestHttpxContract(ResourceContract[httpx.Client]):
    expected: ClassVar[dict[str, bool]] = {"ready": True}

    def open_resource(self, *, capacity: int = 16) -> Resource[httpx.Client]:
        return client(
            capacity=capacity,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"ready": True})
            ),
        )

    def operation(self, value: httpx.Client) -> object:
        return value.get("https://fixture.test").json()


class TestSqliteContract(ResourceContract[sqlite3.Connection]):
    expected = (7,)

    def open_resource(self, *, capacity: int = 16) -> Resource[sqlite3.Connection]:
        return database(":memory:", capacity=capacity)

    def operation(self, value: sqlite3.Connection) -> object:
        return value.execute("SELECT 7").fetchone()


def test_independent_extension_needs_only_public_resource_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "contributor_recipe"
    package.mkdir()
    (package / "__init__.py").write_text("""from pycompose.extensions import Resource
def open_resource(*, capacity=16):
    return Resource(lambda: {"value": 42}, close=lambda data: data.clear(),
                    capacity=capacity)
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        recipe = importlib.import_module("contributor_recipe")

        class Contract(ResourceContract[dict[str, int]]):
            expected = 42

            def open_resource(self, *, capacity: int = 16) -> Resource[dict[str, int]]:
                return recipe.open_resource(capacity=capacity)

            def operation(self, value: dict[str, int]) -> object:
                return value["value"]

        contract = Contract()
        contract.test_roundtrip_and_close()
        contract.test_cancelled_work_retains_physical_capacity()
    finally:
        sys.modules.pop("contributor_recipe", None)
