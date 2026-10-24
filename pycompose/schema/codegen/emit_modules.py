"""Python emission: the runtime tables and the m3 package's exports.

The validator registry embeds the whole catalog as adjacent literals, so the
runtime reads no file; payload contracts type each action's input; the exports
are the package's import surface.
"""

import json
import keyword
import re
from typing import Any

from pycompose.schema.codegen.literals import (
    GENERATED_NOTICE,
    python_adjacent_statements,
)
from pycompose.schema.codegen.rules import die, supported, version_key


def render_payloads(registry: dict[str, Any]) -> str:
    """Generate Python input payload contracts from registry action fields."""
    actions = registry["actions"]
    names = {
        action_id: "".join(
            part[:1].upper() + part[1:]
            for part in re.findall(r"[A-Za-z0-9]+", action_id)
        )
        + "Payload"
        for action_id in sorted(actions)
    }
    if len(set(names.values())) != len(names) or any(
        not name.isidentifier() for name in names.values()
    ):
        die("action ids must produce unique Python payload names")
    imports = {"TypedDict"}
    declarations = []
    simple_types = {
        "string": "str",
        "color": "str",
        "resource": "str",
        "actionId": "str",
        "boolean": "bool",
        "integer": "int",
        "durationMs": "int",
        "number": "int | float",
        "dp": "int | float",
        "modifier": "dict[str, JsonValue]",
    }
    uses_json = False
    for action_id, name in names.items():
        fields = {}
        for field_name, prop in sorted(actions[action_id].get("payload", {}).items()):
            if prop["type"] == "enum":
                imports.add("Literal")
                annotation = (
                    "Literal["
                    + ", ".join(json.dumps(value) for value in sorted(prop["values"]))
                    + "]"
                )
            else:
                annotation = simple_types[prop["type"]]
            uses_json |= prop["type"] == "modifier"
            if not prop.get("required", False):
                imports.add("NotRequired")
                annotation = f"NotRequired[{annotation}]"
            fields[field_name] = annotation
        payload = actions[action_id].get("payload", {})
        if all(
            field.isidentifier() and not keyword.iskeyword(field) for field in payload
        ):
            body = "\n".join(
                f"    {field}: {annotation}" for field, annotation in fields.items()
            )
            declarations.append(f"class {name}(TypedDict):\n" + (body or "    pass"))
        else:
            declarations.append(
                f'{name} = TypedDict(\n    "{name}",\n    {{\n'
                + "\n".join(
                    f"        {json.dumps(field)}: {annotation},"
                    for field, annotation in fields.items()
                )
                + "\n    },\n)"
            )
    return (
        f"# {GENERATED_NOTICE}\n"
        '"""Generated host action input payload contracts."""\n\n'
        "from __future__ import annotations\n\n"
        f"from typing import {', '.join(sorted(imports))}\n"
        + ("\nfrom pycompose.core.props import JsonValue\n" if uses_json else "")
        + "\n__all__ = [\n"
        + "".join(f'    "{name}",\n' for name in sorted(names.values()))
        + "]\n\n\n"
        + "\n\n\n".join(declarations)
        + "\n"
    )


def render_validators(registry: dict[str, Any]) -> str:
    """Render typed runtime tables directly from the SSOT registry."""
    action_ids = sorted(registry.get("actions", {}))
    ids = [json.dumps(action_id) for action_id in action_ids]
    if len(ids) == 1:
        action_tuple = f"({ids[0]},)"
    elif ids:
        action_tuple = "(" + ", ".join(ids) + ")"
    else:
        action_tuple = "()"
    raw = json.dumps(registry, sort_keys=True, separators=(",", ":"))
    # Adjacent literals embed the entire registry without a runtime file read.
    literals = "\n".join(python_adjacent_statements(raw))
    minimum_schema = min(supported(registry), key=version_key)
    body = (
        f"# {GENERATED_NOTICE}\n"
        '"""Generated component, prop, children and action validation tables."""\n\n'
        "from __future__ import annotations\n\n"
        "import json\n\n"
        "from pycompose.core.registry_types import Registry\n\n"
        '__all__ = [\n    "KNOWN_ACTION_IDS",\n    "MIN_LIBRARY_VERSION",\n'
        '    "MIN_SCHEMA_VERSION",\n    "REGISTRY",\n    "SCHEMA_VERSION",\n]\n\n'
        f"SCHEMA_VERSION: str = {json.dumps(registry['schemaVersion'])}\n"
        f"MIN_SCHEMA_VERSION: str = {json.dumps(minimum_schema)}\n"
        f"MIN_LIBRARY_VERSION: str = {json.dumps(registry['minLibraryVersion'])}\n"
        f"KNOWN_ACTION_IDS: tuple[str, ...] = {action_tuple}\n"
        f"REGISTRY: Registry = Registry.from_mapping(\n    json.loads(\n{literals}\n"
        "    )\n)\n"
    )
    return body


def render_python_exports(
    registry: dict[str, Any], package: str = "pycompose.m3"
) -> str:
    """Generate the import surface for all supported native components.

    Args:
        registry: The parsed schema.
        package: The package the constructors live in. The library ships the
            full catalog under ``pycompose.m3``; a per-app slice (ADR-0014)
            ships its own subset under a bare ``m3``, because importing the
            library's full set would bring back every component the app just
            declined to ship.

    Returns:
        The generated ``__init__.py``.
    """
    names = sorted(registry["components"])
    # Sorted by module, because the pre-commit isort hook would otherwise
    # reorder a file nobody may hand-edit and `gen.py --check` would then fail
    # forever on it -- the same two-gates-revert-each-other trap as ktlint
    # against the Kotlin adapters. "pycompose.m3.generated_components" sorts
    # after "pycompose.components.modifiers"; a bare "m3" sorts before it, so
    # the order genuinely differs between the library and an app slice.
    imports = [
        (f"{package}.generated_components", names),
        ("pycompose.components.modifiers", ["Modifier"]),
    ]
    blocks = [
        f"from {module} import ("
        + "".join(f"\n    {name}," for name in entries)
        + "\n)"
        for module, entries in sorted(imports, key=lambda item: item[0])
    ]
    return "\n".join(
        [
            f"# {GENERATED_NOTICE}",
            '"""Native components backed by the shared manifest."""',
            "",
            *blocks,
            "",
            "__all__ = [",
            *(f'    "{name}",' for name in sorted([*names, "Modifier"])),
            "]",
            "",
        ]
    )
