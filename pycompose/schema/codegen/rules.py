"""Catalog rules: the loader and registry-level validator seams.

Validates registry structure the codegen trusts: versions, actions and
components, orchestrating the delegated prop and state validators (imported
lazily -- the house pattern -- so the module graph stays acyclic).
"""

import json
import re
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[3]

PACKAGED_CATALOG = ROOT / "pycompose" / "schema" / "components.json"
"""The catalog as shipped in the wheel, for an app with no repo checkout."""

SCHEMA_PATH = ROOT / "schema/components.json"
if not SCHEMA_PATH.is_file():
    # An installed wheel has no repository above it.
    SCHEMA_PATH = PACKAGED_CATALOG

PROP_TYPE_VOCABULARY = frozenset(
    {
        "actionId",
        "boolean",
        "color",
        "dp",
        "durationMs",
        "enum",
        "integer",
        "modifier",
        "value",
        "number",
        "string",
        "resource",
    }
)


STABILITIES = frozenset({"beta", "experimental", "stable"})


SLOT_NAME = re.compile(r"^[a-z][A-Za-z0-9]*$")
"""Named slots are ``camelCase`` on the wire, so no spelling is invented."""


NATIVE_PARAMETER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


DOTTED_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
"""A Kotlin package or type name: a dotted path of simple identifiers."""


RESERVED_SLOTS = frozenset({"children", "id", "modifier", "props"})

#: Keys a slot entry may carry. Anything else is a typo, not a convention.


SLOT_KEYS = frozenset({"native", "kind", "nullable", "consume"})

#: Keys an interaction entry may carry. Anything else is a typo.


SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def die(message: str) -> NoReturn:
    """Abort codegen with a message.

    Typed ``NoReturn`` rather than ``None`` because every call site is a guard:
    ``if not isinstance(x, dict): die(...)`` only narrows ``x`` if the compiler
    knows the branch does not continue.
    """
    raise SystemExit(f"gen.py: {message}")


def load_registry() -> dict[str, Any]:
    """Read and structurally validate ``schema/components.json``."""
    try:
        raw = SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        die(f"cannot read {SCHEMA_PATH}: {exc}")
    try:
        registry: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        die(f"invalid JSON in {SCHEMA_PATH}: {exc}")
    _validate_registry(registry)
    return registry


def _validate_registry(registry: dict[str, Any]) -> None:
    for key in ("schemaVersion", "minLibraryVersion", "components", "actions"):
        if key not in registry:
            die(f"missing top-level key {key!r} in components.json")
    if not isinstance(registry["schemaVersion"], str):
        die("schemaVersion must be a string")
    require_semver(registry["schemaVersion"], "schemaVersion")
    min_library = registry["minLibraryVersion"]
    if not isinstance(min_library, str):
        die("minLibraryVersion must be a string")
    require_semver(min_library, "minLibraryVersion")

    components = registry["components"]
    if not isinstance(components, dict) or not components:
        die("'components' must be a non-empty object")
    for name, comp in sorted(components.items()):
        _validate_component(name, comp)
    _validate_versions(registry)

    actions = registry["actions"]
    if not isinstance(actions, dict):
        die("'actions' must be an object")
    for action_id, action in sorted(actions.items()):
        from pycompose.schema.codegen.prop_rules import _validate_action

        _validate_action(action_id, action)
    _validate_action_refs(registry)
    _validate_effects(registry.get("effects", {}))
    _validate_lifecycle(registry.get("lifecycle", {}))
    modifiers = registry.get("modifiers", {})
    if not isinstance(modifiers, dict):
        die("'modifiers' must be an object")
    for name, modifier in sorted(modifiers.items()):
        if not isinstance(modifier, dict) or not isinstance(
            modifier.get("props"), dict
        ):
            die(f"modifier {name!r} needs a props object")
        from pycompose.schema.codegen.prop_rules import _validate_prop

        for prop_name, prop in sorted(modifier["props"].items()):
            _validate_prop(name, prop_name, prop)
    from pycompose.schema.codegen.values import validate_definitions

    validate_definitions(registry)


def _validate_effects(effects: object) -> None:
    """Validate the declared effect kinds and their payload contracts."""
    from pycompose.schema.codegen.prop_rules import _validate_action

    if not isinstance(effects, dict):
        die("'effects' must be an object")
    for kind, effect in sorted(effects.items()):
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", kind) is None:
            die(f"effect kind {kind!r} must be a PascalCase identifier")
        _validate_action(kind, effect)


def _validate_lifecycle(lifecycle: object) -> None:
    """Validate host-initiated lifecycle events and their payload contracts."""
    from pycompose.schema.codegen.prop_rules import _validate_action

    if not isinstance(lifecycle, dict):
        die("'lifecycle' must be an object")
    for event, body in sorted(lifecycle.items()):
        if re.fullmatch(r"on[A-Z][A-Za-z0-9]*", event) is None:
            die(f"lifecycle event {event!r} must be an onXxx identifier")
        _validate_action(event, body)


def require_semver(value: str, field: str) -> None:
    if not isinstance(value, str) or SEMVER_PATTERN.fullmatch(value) is None:
        die(f"{field} must be MAJOR.MINOR.PATCH semver, got {value!r}")


def version_key(value: str) -> tuple[int, ...]:
    return tuple(map(int, value.split(".")))


def supported(registry: dict[str, Any]) -> list[str]:
    versions: list[str] = registry.get(
        "supportedSchemaVersions", [registry["schemaVersion"]]
    )
    return versions


def _validate_versions(registry: dict[str, Any]) -> None:
    supported_versions = supported(registry)
    if (
        not isinstance(supported_versions, list)
        or not supported_versions
        or registry["schemaVersion"] not in supported_versions
    ):
        die("supportedSchemaVersions must include the current schema")
    for version in supported_versions:
        require_semver(version, "supportedSchemaVersions")
    if len(set(supported_versions)) != len(supported_versions):
        die("supportedSchemaVersions must be unique")
    if max(supported_versions, key=version_key) != registry["schemaVersion"]:
        die("schemaVersion must be the newest supported schema")
    for spec in registry["components"].values():
        for definition in [spec, *spec["props"].values()]:
            if "since" in definition:
                require_semver(definition["since"], "since")
                if definition["since"] not in supported_versions:
                    die("since must refer to a supported schema")


def _validate_action_refs(registry: dict[str, Any]) -> None:
    declared = set(registry["actions"])
    for name, comp in sorted(registry["components"].items()):
        for prop_name, prop in sorted(comp["props"].items()):
            if prop.get("type") != "actionId" or "default" not in prop:
                continue
            default = prop["default"]
            if default not in declared:
                die(
                    f"component {name}.{prop_name} defaults to action "
                    f"{default!r} which is not declared in 'actions'"
                )


def _validate_opt_in(name: str, comp: dict[str, Any]) -> None:
    """Check a component's declared opt-in markers are usable annotation names.

    Mirrors ``valueTypes.*.optIn``: the pin decided which markers a declaration
    needs, and this only refuses a list that is malformed. Sorted and unique
    keeps the generated ``@file:OptIn`` byte-stable.

    Args:
        name: Component name, for error messages.
        comp: The component's raw schema entry.
    """
    markers = comp.get("optIn", [])
    if markers != sorted(set(markers)) or not all(
        isinstance(marker, str) and marker for marker in markers
    ):
        die(f"component {name!r} optIn must be sorted, unique annotation names")


def _validate_component(name: str, comp: dict[str, Any]) -> None:
    if not isinstance(comp, dict):
        die(f"component {name!r} must be an object")
    from pycompose.schema.codegen.prop_rules import (
        _validate_children,
        _validate_prop,
        _validate_scope,
        _validate_slots,
    )
    from pycompose.schema.codegen.state_rules import (
        _validate_interaction,
        _validate_state,
    )

    if not isinstance(comp.get("category"), str) or not comp["category"]:
        die(f"component {name!r} needs a non-empty 'category'")
    package = comp.get("package")
    if not isinstance(package, str) or DOTTED_NAME.fullmatch(package) is None:
        die(f"component {name!r} needs a dotted 'package' the pin declares it in")
    if comp.get("stability") not in STABILITIES:
        die(f"component {name!r} has unknown stability {comp.get('stability')!r}")
    _validate_opt_in(name, comp)
    _validate_scope(name, comp)
    props = comp.get("props")
    if not isinstance(props, dict):
        die(f"component {name!r} needs a 'props' object")
    for prop_name, prop in sorted(props.items()):
        _validate_prop(name, prop_name, prop)
    children = comp.get("children")
    if not isinstance(children, dict):
        die(f"component {name!r} needs a 'children' object")
    _validate_children(name, children)
    _validate_slots(name, props, children, comp.get("slots", {}))
    _validate_interaction(
        name, props, children, comp.get("slots", {}), comp.get("interaction")
    )
    _validate_state(name, props, children, comp.get("slots", {}), comp.get("state"))
