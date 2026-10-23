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
from pycompose.schema.codegen.overloads import groups, keywords, python_name
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
    components = registry["components"]
    names = sorted(components)
    overloaded = groups(components)
    lines = [
        f"# {GENERATED_NOTICE}",
        "# ruff: noqa: PLR0912 -- one branch per slot; the schema sets the count.",
        f'"""Typed native component constructors; import from {package}."""',
        "",
        "from __future__ import annotations",
        "",
        "from collections.abc import Callable, Sequence",
        "from typing import Any, Literal, cast" + (", overload" if overloaded else ""),
        "",
        "from pycompose.components.base import ActionTarget, Component, PropValue",
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
    # An overload subclasses its primary's public name, so primaries come first.
    for name, spec in sorted(components.items(), key=lambda i: "overloadOf" in i[1]):
        primary = spec.get("overloadOf")
        if name in overloaded:
            lines.extend(_python_constructor(name, spec, class_name=f"_{name}"))
            members = {extra: components[extra] for extra in overloaded[name]}
            lines.extend(_python_dispatcher(name, spec, members))
        else:
            lines.extend(_python_constructor(name, spec, base=primary or "Component"))
    for name, overloads in sorted(overloaded.items()):
        listed = ", ".join(overloads) + ("," if len(overloads) == 1 else "")
        lines.append(f"{name}.overloads = ({listed})")
    return "\n".join(lines).rstrip() + "\n"


def _python_prop(name: str) -> str:
    return python_name(name)


def _python_type(component: str, name: str, prop: dict[str, Any]) -> str:
    if prop["type"] == "enum":
        return f"_{component}{name[:1].upper() + name[1:]}"
    if "valueType" in prop:
        return "JsonValue"
    return {
        "string": "str",
        "color": "str",
        "resource": "str",
        "actionId": "ActionTarget",
        "boolean": "bool",
        "integer": "int",
        "durationMs": "int",
        "number": "int | float",
        "dp": "int | float",
        "modifier": "Modifier",
    }[prop["type"]]


def _native_name(name: str, spec: dict[str, Any]) -> str:
    """Return the native callable a schema entry binds."""
    source = spec.get("source")
    if isinstance(source, dict):
        native = source.get("name")
        if isinstance(native, str):
            return native
    return name


def _python_class_docstring(native: str) -> list[str]:
    """Render the generated class docstring, wrapped when the summary is long.

    Args:
        native: The native callable the schema entry binds.

    Returns:
        The docstring's source lines.
    """
    summary = f"Native {native}; props and defaults follow the component manifest."
    if len(f'    """{summary}"""') <= 88:
        return [f'    """{summary}"""']
    return [
        f'    """Native {native};',
        '    props and defaults follow the component manifest."""',
    ]


def _python_constructor(
    name: str,
    spec: dict[str, Any],
    *,
    class_name: str | None = None,
    base: str = "Component",
) -> list[str]:
    props = spec["props"]
    alias = spec["children"].get("kind")
    lines = [
        f"class {class_name or name}({base}):",
        *_python_class_docstring(_native_name(name, spec)),
        "",
        "    __slots__ = ()",
        f'    component_type = "{name}"',
        *(_keyword_sets(spec) if class_name or base != "Component" else []),
        "",
        "    def __init__(",
        "        self,",
        "        *contents: Node," if spec["children"]["allowed"] else "        *,",
        "        id: str | None = None,",
    ]
    signature, arguments = _python_signature(name, spec)
    if spec["children"]["allowed"]:
        arguments = {
            "*contents": "Children given in order, as Compose's content lambda.",
            **arguments,
        }
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
    if spec["children"]["allowed"]:
        lines.extend(
            [
                "",
                "        Raises:",
                "            IrValidationError: If children are given twice.",
            ]
        )
    lines.extend(['        """', "        props: dict[str, PropValue] = {}"])
    for field, prop in sorted(props.items()):
        python_name = _python_prop(field)
        if field == "modifier" or "protocol" in prop:
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
    if spec["children"]["allowed"] and alias == "items":
        # With item, construction becomes a windowed declaration before this
        # runs (Component.__new__), so a key here is one given without it.
        lines.extend(
            [
                "        if key is not None or item is not None:",
                '            raise IrValidationError("key= needs item=", node_id=id)',
            ]
        )
    if spec["children"]["allowed"] and alias in {"content", "items"}:
        source = "cast(Content, items)" if alias == "items" else alias
        lines.extend(
            [
                f"        if {alias} is not None:",
                "            if children:",
                "                raise IrValidationError(",
                '                    "cannot supply both slot and children", '
                "node_id=id",
                "                )",
                f'            children = content_nodes({source}, key="{alias}")',
            ]
        )
    children = "()"
    if spec["children"]["allowed"]:
        lines.extend(
            [
                "        if contents and children:",
                "            raise IrValidationError(",
                '                "children given positionally and by name", node_id=id',
                "            )",
                "        normalized = content_nodes(contents or children, "
                'key="children")',
            ]
        )
        children = "normalized"
    slot_lines, children = _python_slot_body(spec, children)
    lines.extend(slot_lines)
    modifier = ", modifier=modifier" if "modifier" in props else ""
    invocation = f"id=id, children={children}{modifier}, **props"
    # An overload subclasses its primary for its type, not its construction.
    call = "super().__init__" if base == "Component" else "Component.__init__"
    if base != "Component":
        invocation = f"self, {invocation}"
    if len(f"        {call}({invocation})") > 88:
        lines.extend([f"        {call}(", f"            {invocation}", "        )"])
    else:
        lines.append(f"        {call}({invocation})")
    return [*lines, "", ""]


def _keyword_sets(spec: dict[str, Any]) -> list[str]:
    """Render the keywords an overload requires and accepts, for dispatch."""
    lines = []
    for attribute, values in zip(
        ("required_keywords", "accepted_keywords"), keywords(spec), strict=True
    ):
        if not values:
            lines.append(f"    {attribute} = frozenset()")
            continue
        lines.extend(
            [
                f"    {attribute} = frozenset(",
                "        {",
                *(f'            "{value}",' for value in sorted(values)),
                "        }",
                "    )",
            ]
        )
    return lines


def _python_dispatcher(
    name: str, spec: dict[str, Any], extras: dict[str, dict[str, Any]]
) -> list[str]:
    """Render a primary's public class: one typed ``__new__`` per overload.

    Args:
        name: The primary's component name.
        spec: The primary's entry.
        extras: Its overloads' entries, by name.

    Returns:
        The class's source lines.
    """
    lines = [
        f"class {name}(_{name}):",
        f'    """Native {_native_name(name, spec)}; keywords choose the overload."""',
        "",
        "    __slots__ = ()",
        "",
    ]
    for target, entry in {name: spec, **extras}.items():
        signature, _ = _python_signature(target, entry)
        lines.extend(
            [
                "    @overload",
                "    def __new__(",
                "        cls,",
                "        *contents: Node,"
                if entry["children"]["allowed"]
                else "        *,",
                "        id: str | None = None,",
                *signature,
                f"    ) -> {target}: ...",
            ]
        )
    lines.extend(
        [
            "    def __new__(cls, *contents: Any, **kwargs: Any) -> Any:",
            '        """Construct the overload the keywords select.',
            "",
            "        Args:",
            "            *contents: Children given in order.",
            "            **kwargs: The chosen overload's keyword arguments.",
            "",
            "        Returns:",
            "            An instance of that overload.",
            '        """',
            "        return super().__new__(cls, *contents, **kwargs)",
            "",
            "",
        ]
    )
    return lines


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
        if "protocol" in prop:
            continue
        python_name = _python_prop(field)
        annotation, description = _python_argument(name, field, prop)
        lines.append(f"        {python_name}: {annotation},")
        arguments[python_name] = description
    alias = spec["children"].get("kind")
    if spec["children"]["allowed"]:
        lines.append("        children: Content = (),")
        arguments["children"] = "Ordered child nodes with stable keys."
        if alias == "content":
            lines.append(f"        {alias}: Content | None = None,")
            arguments[alias] = f"Alternative spelling for {alias} children."
        if alias == "items":
            lines.extend(
                [
                    "        items: Content | Sequence[Any] | None = None,",
                    "        key: Callable[[Any], str | int] | None = None,",
                    "        item: Callable[[Any], Node] | None = None,",
                ]
            )
            arguments["items"] = (
                "The children, or with item the data whose window the host composes."
            )
            arguments["key"] = "Each item's stable key, required with item."
            arguments["item"] = "Builds one item's node; the host asks for which."
    for slot_name, slot in sorted(spec.get("slots", {}).items()):
        slot_arg = _python_prop(slot_name)
        lines.append(f"        {slot_arg}: Content | None = None,")
        native = slot.get("native")
        arguments[slot_arg] = (
            f"Nodes for the native {native} slot."
            if native
            else f"Nodes the host composes for the {slot_name} slot."
        )
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
