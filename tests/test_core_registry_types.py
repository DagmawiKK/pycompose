"""core.registry_types: registry types round-trip schema/components.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pycompose.core.registry_types import ComponentDef, Registry
from pycompose.errors import ComponentRegistryError

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS_PATH = ROOT / "schema" / "components.json"


def _raw() -> dict:
    return json.loads(COMPONENTS_PATH.read_text(encoding="utf-8"))


def test_registry_round_trips_components_json() -> None:
    raw = _raw()
    registry = Registry.from_mapping(raw)
    assert registry.to_mapping() == raw


def test_registry_lookups() -> None:
    registry = Registry.from_mapping(_raw())
    text: ComponentDef = registry.component("Text")
    assert text.category == "typography"
    assert text.stability == "stable"
    assert text.props["text"].required is True
    assert text.children.allowed is False
    assert "Text" in registry.component_names()


def test_registry_exposes_action_payloads() -> None:
    registry = Registry.from_mapping(_raw())
    increment = registry.action("increment")
    assert increment.payload["by"].type == "integer"
    assert increment.payload["by"].has_default is True
    assert increment.payload["by"].default == 1
    assert "increment" in registry.action_ids()


def test_registry_rejects_unknown_component() -> None:
    registry = Registry.from_mapping(_raw())
    with pytest.raises(ComponentRegistryError) as excinfo:
        registry.component("DoesNotExist")
    assert "component='DoesNotExist'" in str(excinfo.value)


def test_registry_rejects_malformed_registry() -> None:
    raw = _raw()
    raw["components"]["Text"]["children"] = {"allowed": "yes"}
    with pytest.raises(ComponentRegistryError):
        Registry.from_mapping(raw)


def test_registry_rejects_a_repeated_schema_version() -> None:
    raw = _raw()
    raw["supportedSchemaVersions"] = [
        *raw["supportedSchemaVersions"],
        raw["schemaVersion"],
    ]
    with pytest.raises(ComponentRegistryError) as excinfo:
        Registry.from_mapping(raw)
    assert "unique" in str(excinfo.value)
