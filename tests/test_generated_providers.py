"""Provider family: lambdas, coercion and refusals in generated adapters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pycompose_codegen.emit.adapters.assemble import render
from test_generated_adapters import (
    SCHEMA_PATH,
    components,
)


def test_a_provider_prop_becomes_a_lambda_reading_the_snapshot_value() -> None:
    """``progress: () -> Float`` is a parameter the app cannot name.

    The app states a number in the snapshot; the adapter hands Compose a lambda
    that reads it. The wire carries a Double, so the pinned return type decides
    the conversion instead of a cast the generator picked for itself.
    """
    block = render("LinearProgressIndicator", components()["LinearProgressIndicator"])
    assert "val progressValue = model.props.progress" in block
    assert "progress = { progressValue.toFloat() }" in block


@pytest.mark.parametrize(
    ("prop_type", "conversion"),
    [("number", "toFloat"), ("integer", "toFloat")],
)
def test_a_provider_coerces_the_wire_type_it_was_given(
    prop_type: str, conversion: str
) -> None:
    entry = {
        "package": "androidx.compose.material3",
        "children": {"allowed": False},
        "props": {
            "value": {
                "type": prop_type,
                "required": True,
                "provider": {"native": "progress", "returns": "Float"},
            }
        },
    }
    assert f"progress = {{ valueValue.{conversion}() }}" in render(
        "LinearProgressIndicator", entry
    )


def test_a_provider_refuses_a_return_type_it_cannot_coerce() -> None:
    """A mistyped ``returns`` must fail generation, not become a silent cast."""
    entry = {
        "package": "androidx.compose.material3",
        "children": {"allowed": False},
        "props": {
            "progress": {
                "type": "number",
                "required": True,
                "provider": {"native": "progress", "returns": "Color"},
            }
        },
    }
    assert render("LinearProgressIndicator", entry) == ""


def test_a_value_prop_can_be_provided_through_its_family_resolver() -> None:
    """A family value is a lambda return too, with the resolver naming the type."""
    entry = {
        "package": "androidx.compose.material3",
        "children": {"allowed": False},
        "props": {
            "windowInsets": {
                "type": "value",
                "valueType": "WindowInsets",
                "required": True,
                "provider": {
                    "native": "contentWindowInsets",
                    "returns": "WindowInsets",
                },
            }
        },
    }
    block = render("ModalBottomSheet", entry)
    assert "val windowInsetsValue =" in block
    assert "contentWindowInsets = { windowInsetsValue }" in block


def test_every_provider_in_the_catalog_is_required_and_non_nullable() -> None:
    """An absent value would need two call shapes; the schema forbids that."""
    providers = [
        (name, prop, spec)
        for name, entry in components().items()
        for prop, spec in entry["props"].items()
        if "provider" in spec
    ]
    assert providers, "the catalog should exercise a provider"
    for name, prop, spec in providers:
        assert spec.get("required"), f"{name}.{prop} provider must be required"
        assert not spec.get("nullable"), f"{name}.{prop} provider cannot be nullable"


@pytest.mark.parametrize(
    ("provider", "message"),
    [
        ({"native": "progress"}, "'returns' must be a Kotlin type name"),
        ({"returns": "Float"}, "'native' must be a parameter name"),
        (
            {"native": "progress", "returns": "Float", "cast": "toFloat()"},
            "unknown keys",
        ),
    ],
)
def test_the_schema_refuses_a_malformed_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: dict, message: str
) -> None:
    """The two keys the generator reads are both required, and nothing else."""
    from pycompose_codegen.emit import main, rules

    registry = json.loads(SCHEMA_PATH.read_text())
    registry["components"]["LinearProgressIndicator"]["props"]["progress"][
        "provider"
    ] = provider
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match=message):
        main.load_registry()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"required": False}, "needs the prop to be required"),
        ({"nullable": True}, "cannot come from a nullable prop"),
    ],
)
def test_the_schema_refuses_a_provider_it_cannot_always_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict, message: str
) -> None:
    from pycompose_codegen.emit import main, rules

    registry = json.loads(SCHEMA_PATH.read_text())
    registry["components"]["LinearProgressIndicator"]["props"]["progress"].update(
        change
    )
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match=message):
        main.load_registry()


def test_the_schema_refuses_a_provider_on_a_modifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A modifier is not a value: the app cannot state one through a lambda."""
    from pycompose_codegen.emit import main, rules

    registry = json.loads(SCHEMA_PATH.read_text())
    registry["components"]["LinearProgressIndicator"]["props"]["modifier"] = {
        "type": "modifier",
        "required": True,
        "provider": {"native": "progress", "returns": "Float"},
    }
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match="cannot wrap a modifier prop"):
        main.load_registry()
