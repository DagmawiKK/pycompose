"""Python emission: runtime tables, the m3 component surface and exports.

Covers the validator registry (adjacent literals), generated payloads and
the components a Compose host composes.
"""

import json
import keyword
import re
import textwrap
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


def render_python_components(
    registry: dict[str, Any], package: str = "pycompose.m3"
) -> str:
    """Generate typed Python constructors from the native manifest.

    Args:
        registry: The parsed schema.
        package: The package these are imported from, named in the module
            docstring so an app slice does not point readers at the catalog.

    Returns:
        The generated module.
    """
    names = sorted(registry["components"])
    lines = [
        f"# {GENERATED_NOTICE}",
        f'"""Typed native component constructors; import from {package}."""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Literal",
        "",
        "from pycompose.components.base import Component",
        "from pycompose.components.modifiers import Modifier",
        "from pycompose.composition import Content, content_nodes, slot_nodes",
        "from pycompose.core.node import Node",
        "from pycompose.core.props import JsonValue",
        "from pycompose.errors import IrValidationError",
        "",
        "__all__ = [",
        *(f'    "{name}",' for name in names),
        "]",
        "",
        "",
    ]
    if any(
        p.get("nullable")
        for s in registry["components"].values()
        for p in s["props"].values()
    ):
        index = lines.index("from pycompose.errors import IrValidationError")
        lines.insert(index, "from pycompose.core.values import UNSET, _Unset")
    for name, spec in sorted(registry["components"].items()):
        for field, prop in sorted(spec["props"].items()):
            # Enum props annotate with their token scale even when they also
            # carry a valueType: the wire value is the bare token string, and
            # the alias autocompletes the scale the validator enforces.
            if prop["type"] == "enum":
                lines.extend(
                    [
                        f"{_python_type(name, field, prop)} = Literal[",
                        *(f"    {json.dumps(value)}," for value in prop["values"]),
                        "]",
                        "",
                    ]
                )
    lines.append("")
    for name, spec in sorted(registry["components"].items()):
        lines.extend(_python_constructor(name, spec))
    return "\n".join(lines).rstrip() + "\n"


def _python_prop(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _python_type(component: str, name: str, prop: dict[str, Any]) -> str:
    if prop["type"] == "enum":
        return f"_{component}{name[:1].upper() + name[1:]}"
    if "valueType" in prop:
        return "JsonValue"
    return {
        "string": "str",
        "color": "str",
        "resource": "str",
        "actionId": "str",
        "boolean": "bool",
        "integer": "int",
        "durationMs": "int",
        "number": "int | float",
        "dp": "int | float",
        "modifier": "Modifier",
    }[prop["type"]]


def _python_class_docstring(name: str) -> list[str]:
    """Render the generated class docstring, wrapped when the name is long.

    Args:
        name: The generated class name.

    Returns:
        The docstring's source lines.
    """
    summary = f"Native {name}; props and defaults follow the component manifest."
    if len(f'    """{summary}"""') <= 88:
        return [f'    """{summary}"""']
    return [
        f'    """Native {name};',
        '    props and defaults follow the component manifest."""',
    ]


def _python_constructor(name: str, spec: dict[str, Any]) -> list[str]:
    props = spec["props"]
    alias = spec["children"].get("kind")
    lines = [
        f"class {name}(Component):",
        *_python_class_docstring(name),
        "",
        "    __slots__ = ()",
        f'    component_type = "{name}"',
        "",
        "    def __init__(",
        "        self,",
        "        *,",
        "        id: str | None = None,",
    ]
    signature, arguments = _python_signature(name, spec)
    lines.extend(signature)
    lines.extend(
        [
            "    ) -> None:",
            f'        """Construct a registered {name}.',
            "",
            "        Args:",
            *(
                line
                for field, description in arguments.items()
                for line in _docstring_arg(field, description)
            ),
        ]
    )
    if spec["children"]["allowed"] and alias in {"content", "items"}:
        lines.extend(
            [
                "",
                "        Raises:",
                "            IrValidationError: If slot and children are both set.",
            ]
        )
    lines.extend(['        """', "        props: dict[str, JsonValue] = {}"])
    for field, prop in sorted(props.items()):
        python_name = _python_prop(field)
        if field == "modifier":
            continue
        if not prop.get("required", False):
            absent = "UNSET" if prop.get("nullable") else "None"
            condition = (
                f"not isinstance({python_name}, _Unset)"
                if prop.get("nullable")
                else f"{python_name} is not {absent}"
            )
            lines.extend(
                [
                    f"        if {condition}:",
                    f'            props["{python_name}"] = {python_name}',
                ]
            )
        else:
            lines.append(f'        props["{python_name}"] = {python_name}')
    if spec["children"]["allowed"] and alias in {"content", "items"}:
        lines.extend(
            [
                f"        if {alias} is not None:",
                "            if children:",
                "                raise IrValidationError(",
                '                    "cannot supply both slot and children", '
                "node_id=id",
                "                )",
                f'            children = content_nodes({alias}, key="{alias}")',
            ]
        )
    children = "()"
    if spec["children"]["allowed"]:
        lines.append('        normalized = content_nodes(children, key="children")')
        children = "normalized"
    slot_lines, children = _python_slot_body(spec, children)
    lines.extend(slot_lines)
    modifier = ", modifier=modifier" if "modifier" in props else ""
    invocation = f"id=id, children={children}{modifier}, **props"
    if len(invocation) + len("        super().__init__()") > 88:
        lines.extend(
            ["        super().__init__(", f"            {invocation}", "        )"]
        )
    else:
        lines.append(f"        super().__init__({invocation})")
    return [*lines, "", ""]


def _python_signature(
    name: str, spec: dict[str, Any]
) -> tuple[list[str], dict[str, str]]:
    """Render one component's keyword parameters and their docstring lines.

    Args:
        name: Component name, for prop annotations.
        spec: The component's manifest entry.

    Returns:
        Signature lines, then one description per parameter.
    """
    lines: list[str] = []
    arguments = {"id": "Stable instance key; None derives the node's path id."}
    for field, prop in sorted(spec["props"].items()):
        python_name = _python_prop(field)
        annotation, description = _python_argument(name, field, prop)
        lines.append(f"        {python_name}: {annotation},")
        arguments[python_name] = description
    alias = spec["children"].get("kind")
    if spec["children"]["allowed"]:
        lines.append("        children: Content = (),")
        arguments["children"] = "Ordered child nodes with stable keys."
        if alias in {"content", "items"}:
            lines.append(f"        {alias}: Content | None = None,")
            arguments[alias] = f"Alternative spelling for {alias} children."
    for slot_name, slot in sorted(spec.get("slots", {}).items()):
        slot_arg = _python_prop(slot_name)
        lines.append(f"        {slot_arg}: Content | None = None,")
        arguments[slot_arg] = f"Nodes for the native {slot['native']} slot."
    return lines, arguments


def _python_slot_body(spec: dict[str, Any], children: str) -> tuple[list[str], str]:
    """Render the statements that collect one component's named slots.

    Args:
        spec: The component's manifest entry.
        children: Expression for the primary children so far.

    Returns:
        Body lines, then the child expression the constructor passes on.
    """
    if not spec.get("slots"):
        return [], children
    lines = ["        slotted: tuple[Node, ...] = ()"]
    for slot_name, _slot in sorted(spec["slots"].items()):
        slot_arg = _python_prop(slot_name)
        call = f"slotted += slot_nodes({slot_arg}, "
        lines.append(f"        if {slot_arg} is not None:")
        single = f'{call}key="{slot_name}", slot="{slot_name}")'
        if len(single) + len("            ") <= 88:
            lines.append(f"            {single}")
            continue
        lines.extend(
            [
                "            slotted += slot_nodes(",
                f"                {slot_arg},",
                f'                key="{slot_name}",',
                f'                slot="{slot_name}",',
                "            )",
            ]
        )
    combined = "slotted" if children == "()" else "normalized + slotted"
    return lines, combined


def _docstring_arg(field: str, description: str) -> list[str]:
    """Render one constructor Args entry inside the 88-column budget.

    A long prop name plus its fixed note can cross the formatter's line
    limit, and a generated file must survive the same lint as a hand-written
    one, so the entry wraps at a word boundary under the Args indent.

    Args:
        field: The constructor parameter's name.
        description: Its one-line note.

    Returns:
        The entry's lines, continuations indented under the first.
    """
    wrapped = textwrap.wrap(f"{field}: {description}", width=72) or [f"{field}:"]
    return [f"            {wrapped[0]}"] + [
        f"                {rest}" for rest in wrapped[1:]
    ]


def _python_argument(
    component: str, field: str, prop: dict[str, Any]
) -> tuple[str, str]:
    annotation = _python_type(component, field, prop)
    if prop.get("nullable"):
        annotation += " | None"
    if prop.get("required"):
        return annotation, f"Required native {field}."
    if prop.get("nullable"):
        return (
            annotation + " | _Unset = UNSET",
            f"Native {field}; omitted uses its default; None is null.",
        )
    return annotation + " | None = None", f"Native {field}; None uses its default."


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
