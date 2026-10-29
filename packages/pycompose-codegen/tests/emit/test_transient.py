"""The transient wire: a serial-numbered request beside the state rail.

A projection's idempotency comes from comparing desired against settled; an
occurrence has no settled state to compare, and naming a snackbar's "current
value" would be a lie (ADR-0017 decisions 6-8). A transient declaration names
the serial prop the host compares against the last serial it handled under
the node's identity: an identical re-rendered snapshot is a no-op, a bumped
serial shows once, and the occurrence reports the serial back so Python can
correlate the fulfilment with the request.

These tests pin the declaration's Python half: the bounded keys, what the
codegen refuses, and the runtime registry round-trip. What the host does
with a fulfilled serial is a Kotlin seam.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pycompose_codegen.emit.adapters.assemble import render

SCHEMA_PATH = Path(__file__).resolve().parents[4] / "schema" / "catalog.lock.json"

STATEFUL = "ModalNavigationDrawer"


def _load_with(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    """Validate the catalog after one deliberate change.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Pytest monkeypatch fixture.
        mutate: Applies the change to the loaded registry.
    """
    from pycompose_codegen.emit import main, rules

    registry = json.loads(SCHEMA_PATH.read_text())
    mutate(registry)
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    main.load_registry()


def _transient(
    registry: dict[str, Any], updates: dict[str, object] | None = None
) -> None:
    """Give the drawer a valid transient, then apply one deliberate change.

    Args:
        registry: The loaded catalog.
        updates: Keys to overwrite on the otherwise valid block.
    """
    block: dict[str, object] = {
        "kind": "snackbar",
        "native": "hostState",
        "serial": "serial",
        "occurrence": "onDismiss",
    }
    if updates is not None:
        block.update(updates)
    entry = registry["components"][STATEFUL]
    entry["transient"] = block
    entry["props"]["serial"] = {"type": "integer"}
    entry["props"]["onDismiss"] = {
        "type": "actionId",
        "payload": [{"name": "value", "type": "integer"}],
    }


# ---------------------------------------------------------------------------
# The declaration agrees with the props it names
# ---------------------------------------------------------------------------


def test_a_declared_transient_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The serial and its occurrence are ordinary props held by the host."""
    _load_with(tmp_path, monkeypatch, lambda registry: _transient(registry))


# ---------------------------------------------------------------------------
# The shape spec and the validator name the same bounded keys
# ---------------------------------------------------------------------------


def test_the_shape_and_the_validator_agree_on_the_transient_keys() -> None:
    """The spec's properties are one fact with the codegen's key set."""
    from pycompose_codegen.emit.state_rules import TRANSIENT_KEYS

    schema = json.loads(
        (
            Path(__file__).resolve().parents[4] / "schema" / "catalog.schema.json"
        ).read_text()
    )
    block = schema["$defs"]["transientBlock"]
    assert set(block["properties"]) == set(TRANSIENT_KEYS)
    assert set(block["required"]) == set(TRANSIENT_KEYS)


# ---------------------------------------------------------------------------
# The codegen refuses a transient it cannot fulfil faithfully
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("break_it", "expected"),
    [
        (
            lambda registry: registry["components"][STATEFUL].update(transient=3),
            "must be an object",
        ),
        (
            lambda registry: _transient(registry, {"unknown": True}),
            "unknown keys",
        ),
        (
            lambda registry: _transient(registry, {"kind": "toast"}),
            "unknown transient kind",
        ),
        (
            lambda registry: _transient(registry, {"native": "drawerContent"}),
            "repeats another parameter",
        ),
        (
            lambda registry: _transient(registry, {"native": 3}),
            "'native' must be a parameter name",
        ),
        (
            lambda registry: _transient(registry, {"serial": "missing"}),
            "'serial' must name one of the props",
        ),
        (
            lambda registry: _transient(registry, {"occurrence": "missing"}),
            "'occurrence' must name one of the props",
        ),
        (
            lambda registry: _transient(registry, {"occurrence": "open"}),
            "must be an actionId",
        ),
        (
            lambda registry: (
                _transient(registry),
                registry["components"][STATEFUL]["props"]["serial"].update(
                    type="string"
                ),
            ),
            "'serial' must be an integer",
        ),
        (
            lambda registry: (
                _transient(registry),
                registry["components"][STATEFUL]["props"]["onDismiss"].update(
                    type="boolean"
                ),
            ),
            "must be an actionId",
        ),
        (
            lambda registry: (
                _transient(registry),
                registry["components"][STATEFUL]["props"]["onDismiss"]["payload"][
                    0
                ].update(type="boolean"),
            ),
            "needs one integer payload field",
        ),
        (
            lambda registry: (
                _transient(registry),
                registry["components"][STATEFUL]["props"]["onDismiss"][
                    "payload"
                ].append({"name": "extra", "type": "integer"}),
            ),
            "needs one integer payload field",
        ),
    ],
)
def test_the_codegen_refuses_an_unrenderable_transient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    break_it: Callable[[dict[str, Any]], None],
    expected: str,
) -> None:
    """A transient the generator cannot fulfil faithfully is refused.

    An adapter emitted from a half-understood declaration either never shows
    a request or shows it twice, and neither failure is visible from the
    schema alone.
    """
    with pytest.raises(SystemExit, match=expected):
        _load_with(tmp_path, monkeypatch, break_it)


# ---------------------------------------------------------------------------
# The runtime registry carries the declaration, not just the codegen
# ---------------------------------------------------------------------------


def test_the_runtime_registry_round_trips_the_transient() -> None:
    """The registry type keeps the declaration a schema reader can trust."""
    from pycompose.contract.registry_types import ComponentSpec, TransientRule
    from pycompose.errors import ComponentRegistryError

    transient = {
        "kind": "snackbar",
        "native": "hostState",
        "serial": "serial",
        "occurrence": "onDismiss",
    }
    spec = ComponentSpec.from_mapping(
        STATEFUL,
        {
            "category": "layout",
            "stability": "stable",
            "props": {},
            "children": {"allowed": True},
            "transient": transient,
        },
    )
    assert spec.transient is not None
    assert spec.transient.kind == "snackbar"
    assert spec.to_mapping()["transient"] == transient
    with pytest.raises(ComponentRegistryError, match="unknown transient kind"):
        TransientRule.from_mapping(
            {**transient, "kind": "toast"}, where=f"{STATEFUL}.transient"
        )
    with pytest.raises(ComponentRegistryError, match="'native' must be a name"):
        TransientRule.from_mapping(
            {**transient, "native": 3}, where=f"{STATEFUL}.transient"
        )


SNACKBAR = {
    "props": {
        "message": {"type": "string", "required": True},
        "actionLabel": {"type": "string"},
        "serial": {"type": "integer", "required": True},
        "onDismiss": {
            "type": "actionId",
            "payload": [{"name": "serial", "type": "integer"}],
        },
        "modifier": {"type": "modifier"},
    },
    "children": {"allowed": False},
    "transient": {
        "kind": "snackbar",
        "native": "hostState",
        "serial": "serial",
        "occurrence": "onDismiss",
    },
}
"""A snackbar host entry as the catalog will carry it, before the catalog does."""


def test_the_adapter_requests_the_transient_with_every_prop() -> None:
    """The host consumes all four inputs on the component's behalf."""
    adapter = render("SnackbarHost", SNACKBAR)
    assert (
        "val hostStateValue = context.snackbar(model.id, "
        "actionLabel = model.props.actionLabel, message = model.props.message, "
        "onDismiss = model.props.onDismiss, serial = model.props.serial)" in adapter
    )
    assert "hostState = hostStateValue" in adapter
    # No prop reaches the component itself: the host consumes them all, and
    # the component's modifier stays its own argument.
    component = adapter.split("SnackbarHost(")[1].split(")")[0]
    assert "message" not in component
    assert "serial" not in component
    assert "onDismiss" not in component
    assert "modifier = model.props.modifier" not in adapter
