"""The catalog's shape is declared; the functions stay the deep semantics.

The schema refuses unknown keys and missing required ones, so catalog growth
must touch the declarative spec first. It deliberately declares no vocabulary
enums: closed sets live once in registry_vocabulary and their codegen homes,
and a JSON enum would be a second home the .py-scanning gate cannot see.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from pycompose.codegen import rules

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "schema" / "catalog.lock.json"
SCHEMA = ROOT / "schema" / "catalog.schema.json"


def _catalog() -> dict[str, Any]:
    """Return the SSOT catalog as loaded."""
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _schema() -> dict[str, Any]:
    """Return the declarative catalog shape."""
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_the_catalog_declares_and_matches_its_shape() -> None:
    """The SSOT satisfies its own declarative spec, draft 2020-12."""
    jsonschema.validate(instance=_catalog(), schema=_schema())


def test_the_shape_refuses_an_unknown_top_level_key() -> None:
    """A new section fails until the spec names it: no silent key drift."""
    catalog = _catalog()
    catalog["futureSection"] = {}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=catalog, schema=_schema())


def test_the_shape_refuses_a_missing_required_key() -> None:
    """The four keys the validators require are required here too."""
    catalog = _catalog()
    del catalog["components"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=catalog, schema=_schema())


def test_the_shape_refuses_a_component_missing_a_required_key() -> None:
    """Strictness reaches inside the maps, not just the top level."""
    catalog = _catalog()
    first = next(iter(catalog["components"]))
    del catalog["components"][first]["stability"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=catalog, schema=_schema())


def test_the_shape_declares_no_vocabulary_enums() -> None:
    """No closed set may be restated here; the hub stays the only home."""
    schema = _schema()

    def _enums(node: Any) -> list[Any]:
        if isinstance(node, dict):
            found = [node["enum"]] if "enum" in node else []
            return found + [e for value in node.values() for e in _enums(value)]
        if isinstance(node, list):
            return [e for item in node for e in _enums(item)]
        return []

    assert (
        _enums(schema) == []
    ), "closed vocabularies belong to the hub, not a JSON enum"


def test_the_shape_names_the_transient_block() -> None:
    """A transient is declared beside the state; the spec must name it."""
    catalog = _catalog()
    component = next(iter(catalog["components"].values()))
    component["transient"] = {
        "kind": "snackbar",
        "native": "hostState",
        "serial": "serial",
        "occurrence": "onDismiss",
    }
    jsonschema.validate(instance=catalog, schema=_schema())


def test_the_shape_refuses_an_unknown_transient_key() -> None:
    """The transient block's keys are bounded exactly like the state's."""
    catalog = _catalog()
    component = next(iter(catalog["components"].values()))
    component["transient"] = {
        "kind": "snackbar",
        "native": "hostState",
        "serial": "serial",
        "occurrence": "onDismiss",
        "future": True,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=catalog, schema=_schema())


def test_the_schema_and_the_validator_require_the_same_top_keys() -> None:
    """Required-keys is one fact: the spec and the function cannot drift."""
    assert set(_schema()["required"]) == set(rules.REGISTRY_KEYS)


def test_the_tooltip_trio_shares_a_scope_and_one_visibility_state() -> None:
    """The box owns visibility; its scoped content cannot stand alone."""
    components = _catalog()["components"]
    box = components["TooltipBox"]
    assert box["state"] == {
        "native": "state",
        "kind": "tooltip",
        "value": "visible",
        "report": "onVisibilityChange",
    }
    assert (
        box["slots"]["tooltip"]["provides"] == "androidx.compose.material3.TooltipScope"
    )
    for name in ("PlainTooltip", "RichTooltip"):
        assert (
            components[name]["scope"] == "androidx.compose.material3.TooltipScope"
        ), name
    for name in ("PlainTooltip", "RichTooltip"):
        for prop in components[name]["props"].values():
            if prop["type"] == "color":
                assert prop["valueType"] == "Color"
                assert prop["decode"] == "color"


def test_the_search_input_field_requires_the_callbacks_native_needs() -> None:
    """A native-required callback cannot be omitted on the wire.

    ``SearchBarDefaults.InputField`` always takes query, search and expansion
    callbacks. Optional action ids compile into nullable Kotlin properties and
    a ``context.event`` call that has no action to dispatch, so the schema marks
    the five required parameters required and keeps the icon slots nullable.
    """
    field = _catalog()["components"]["SearchBarInputField"]
    for name in ("query", "expanded", "onQueryChange", "onSearch", "onExpandedChange"):
        assert field["props"][name]["required"] is True, name
    assert set(field["slots"]) == {"placeholder", "leadingIcon", "trailingIcon"}
    assert all(slot["nullable"] for slot in field["slots"].values())
