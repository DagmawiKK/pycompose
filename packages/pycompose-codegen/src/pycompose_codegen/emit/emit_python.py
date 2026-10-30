"""Python emission: the component classes a Compose host composes.

The whole-file renderers -- runtime tables and the package exports -- live in
:mod:`pycompose_codegen.emit.emit_modules`.
"""

import io
import json
import tokenize
from typing import Any

from pycompose_codegen.emit.literals import (
    GENERATED_NOTICE,
    python_adjacent_statements,
)
from pycompose_codegen.emit.overloads import groups, keywords, native_name, python_name
from pycompose_codegen.emit.python_layout import (
    class_docstring,
    class_header,
    docstring_arg,
    overloads_line,
)


def render_python_components(
    registry: dict[str, Any],
    package: str = "pycompose.ui",
    own: dict[str, Any] | None = None,
) -> str:
    """Generate typed Python constructors from the native manifest.

    Args:
        registry: The parsed schema.
        package: The package these are imported from, named in the module
            docstring so an app slice does not point readers at the catalog.
        own: Components of the app's own libraries (its lock slice), which the
            module registers with the runtime catalog when imported.

    Returns:
        The generated module.
    """
    components = registry["components"]
    names = sorted(components)
    overloaded = groups(components)
    lines = [
        "__all__ = [",
        *(f'    "{name}",' for name in names),
        "]",
        "",
        "",
    ]
    if own:
        # The runtime validates against the catalog, which knows only the
        # library's components until the app's own are registered.
        raw = json.dumps(own, sort_keys=True, separators=(",", ":"))
        lines.extend(
            [
                "REGISTRY.extend(",
                "    json.loads(",
                *python_adjacent_statements(raw),
                "    )",
                ")",
                "",
                "",
            ]
        )
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
        lines.append(overloads_line(name, overloads))
    body = "\n".join(lines).rstrip() + "\n"
    header = [
        f"# {GENERATED_NOTICE}",
        "# ruff: noqa: C901, PLR0912 -- one branch per slot; the schema sets them.",
        f'"""Typed native component constructors; import from {package}."""',
        "",
        "from __future__ import annotations",
        "",
        *_imports(body),
        "",
    ]
    return "\n".join(header) + "\n" + body


# Every name a component module may use, by module, in the order isort sorts
# them; a module imports only those its classes use, so neither one library
# package nor an app's slice carries an unused import.
_STANDARD = (
    ("collections.abc", ("Callable", "Sequence")),
    ("typing", ("Any", "Literal", "cast", "overload")),
)
_FIRST_PARTY = (
    ("pycompose.errors", ("IrValidationError",)),
    ("pycompose.model.catalog.lock", ("REGISTRY",)),
    ("pycompose.model.nodes.expressions", ("Expression",)),
    ("pycompose.model.nodes.node", ("Node",)),
    ("pycompose.model.nodes.props", ("JsonValue",)),
    ("pycompose.model.nodes.values", ("UNSET", "_Unset")),
    ("pycompose.ui.component", ("ActionTarget", "Component", "PropValue")),
    ("pycompose.ui.composition", ("Content", "content_nodes", "slot_nodes")),
    ("pycompose.ui.modifier", ("Modifier",)),
)


def _imports(body: str) -> list[str]:
    """The import block for a module body: the names its code uses, not its text."""
    tokens = tokenize.generate_tokens(io.StringIO(body).readline)
    used = {token.string for token in tokens if token.type == tokenize.NAME}

    def block(table: tuple[tuple[str, tuple[str, ...]], ...]) -> list[str]:
        return [
            f"from {module} import {', '.join(n for n in names if n in used)}"
            for module, names in table
            if used.intersection(names)
        ]

    standard = ["import json"] * ("json" in used) + block(_STANDARD)
    return [*standard, "", *block(_FIRST_PARTY)]


def _python_type(component: str, name: str, prop: dict[str, Any]) -> str:
    if prop["type"] == "enum":
        return f"_{component}{name[:1].upper() + name[1:]}"
    if prop["type"] == "color":
        # A colour may follow a holder's stream, evaluated by the host.
        return f"{'JsonValue' if 'valueType' in prop else 'str'} | Expression"
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


def _python_constructor(
    name: str,
    spec: dict[str, Any],
    *,
    class_name: str | None = None,
    base: str = "Component",
) -> list[str]:
    props = spec["props"]
    alias = spec["children"].get("kind")
    header, summary = class_header(class_name or name, base, name)
    lines = [
        header,
        *class_docstring(native_name(name, spec)),
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
            f'        """{summary}',
            "",
            "        Args:",
            *(
                line
                for field, description in arguments.items()
                for line in docstring_arg(field, description)
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
        keyword = python_name(field)
        if field == "modifier" or "protocol" in prop:
            continue
        if not prop.get("required", False):
            absent = "UNSET" if prop.get("nullable") else "None"
            condition = (
                f"not isinstance({keyword}, _Unset)"
                if prop.get("nullable")
                else f"{keyword} is not {absent}"
            )
            lines.extend(
                [
                    f"        if {condition}:",
                    f'            props["{keyword}"] = {keyword}',
                ]
            )
        else:
            lines.append(f'        props["{keyword}"] = {keyword}')
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
        f'    """Native {native_name(name, spec)}; keywords choose the overload."""',
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
        keyword = python_name(field)
        annotation, description = _python_argument(name, field, prop)
        lines.append(f"        {keyword}: {annotation},")
        arguments[keyword] = description
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
        slot_arg = python_name(slot_name)
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
        slot_arg = python_name(slot_name)
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
