"""Assemble the Kotlin adapters that are mechanically derivable.

    python tools/schema/gen.py          # writes GeneratedAdapters.kt too

ADR-0011's addendum ended with "you would only need manual adapters for
non-standard components", and that was optimistic. Roughly half the current
catalog is mechanical; the rest is not, and pretending otherwise would generate
code that does not compile.

An adapter is generated when **every** one of these holds:

* no children -- a component that composes content needs its lambda written by
  hand, because where the children go is the decision
* every prop is a scalar, a modifier, or an actionId
* no prop the host resolves by name, such as a resource

Everything else stays in ``BuiltinComponents.kt``. A test asserts that every
registered component has an adapter in exactly one of the two, so neither file
can quietly fall behind the schema -- which is the failure that produced a blank
screen once already.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.emit.adapters.eligibility import held_props, is_mechanical
from pycompose_codegen.emit.adapters.fragments import Fragments
from pycompose_codegen.emit.adapters.imports import extra_imports
from pycompose_codegen.emit.adapters.policy import native_name, simple
from pycompose_codegen.emit.adapters.props import render_prop
from pycompose_codegen.emit.adapters.slots import (
    children_argument,
    composables,
    named_slot,
)
from pycompose_codegen.emit.adapters.state import host_locals, resolve_constructor
from pycompose_codegen.emit.adapters.text_echo import echoed_text


def render(name: str, entry: dict[str, Any]) -> str:
    """Render one adapter, or an empty string when it cannot be derived.

    A prop is passed only when its generated Kotlin property is non-null, which
    is exactly when the schema marks it required or gives it a default.
    ``Button.enabled`` has a default and passes; an optional prop with no
    declared default is a ``Boolean?`` in the model and is omitted, leaving
    Compose's own default in charge.

    A prop flattened out of a content slot becomes a lambda wrapping the slot's
    declared composable -- ``Text(model.props.text)`` inside ``Button``, or
    ``label = { Text(model.props.label) }`` for ``FilterChip``, which names its
    slot. An ``enum``, ``color`` or ``resource`` is routed through the resolver
    its ``decode`` names, bound to a local first.

    Children and named slots are declared, so the generator no longer guesses
    where a subtree goes: the primary children reach their native parameter, a
    named slot reaches its ``native`` parameter, ``items`` lists them lazily
    with stable keys, and a ``paddingValues`` scope is consumed once on the
    subtree's behalf.

    A component that accepts a host-created interaction source names it in its
    entry: the observing prop is left out of the native arguments, and the
    source the renderer remembers for the node fills its place. A component that
    accepts a host-owned state holder declares it the same way: the props
    carrying Python's desired value and reporting settled changes are left out,
    and the holder the renderer remembers fills the native parameter.

    Args:
        name: The component's schema name.
        entry: Its schema entry.

    Returns:
        The adapter as Kotlin, or an empty string when it cannot be derived.
    """
    if not is_mechanical(entry):
        return ""

    out = Fragments()
    out.arguments.append("modifier = modifier")
    interaction = entry.get("interaction") or {}
    observed = set((interaction.get("observations") or {}).values())
    state = entry.get("state")
    transient = entry.get("transient")
    held = held_props(entry)
    if transient is not None:
        # Every prop of a transient component is a request input the host
        # consumes on its behalf; none names a native parameter of its own.
        held |= set(entry.get("props", {}))
    if not resolve_constructor(state, entry.get("props", {}), out):
        return ""
    held |= echoed_text(entry.get("props", {}), out)
    for prop, spec in entry.get("props", {}).items():
        if "protocol" in spec or prop in observed or prop in held:
            # The host fills the source or the state holder; an observed prop
            # reports state, a held prop carries the app's desired state, and a
            # protocol prop steers the host itself: none names a native parameter.
            continue
        if not render_prop(prop, spec, out):
            return ""
    gate = " && ".join(filter(None, [host_locals(entry, out), *out.gates])) or None
    for slot_name, slot in sorted(entry.get("slots", {}).items()):
        out.arguments.append(named_slot(slot_name, slot))

    children = entry.get("children", {})
    if children.get("allowed"):
        out.arguments.append(children_argument(children, out))

    indent = "                "
    if gate is not None:
        indent += "    "
    node = f"{name}Node"
    prelude = "\n".join(f"                {line}" for line in out.locals)
    call = _call(native_name(name, entry), out, indent, boxed=bool(entry.get("boxed")))
    if gate is not None:
        # The holder stays outside the gate: the state must outlive the
        # composition of the component it projects.
        call = f"                if ({gate}) {{\n{call}\n                }}"
    scope = entry.get("scope")
    registration = f"registerScoped<{simple(scope)}>" if scope else "register"
    return (
        f'            .{registration}("{name}") {{ node, modifier, context ->\n'
        f"                val model = node as {node}\n"
        + (f"{prelude}\n" if prelude else "")
        + f"{call}\n"
        f"            }}"
    )


def _call(native: str, out: Fragments, indent: str, *, boxed: bool) -> str:
    """The native call; one taking no modifier sits in a Box wearing the node's."""
    arguments = out.arguments[1:] if boxed else out.arguments
    body = "\n".join(f"{indent}    {argument}," for argument in arguments)
    tail = ""
    if out.trailing:
        head = " {"
        if out.trailing_parameter is not None:
            head = f" {{ {out.trailing_parameter} ->"
        body_lines = "\n".join(f"{indent}    {line}" for line in out.trailing)
        tail = head + "\n" + body_lines + "\n" + indent + "}"
    call = f"{indent}{native}(\n{body}\n{indent}){tail}"
    if boxed:
        call = f"{indent}Box({out.arguments[0]}) {{\n{call}\n{indent}}}"
    return call


def _scopes(entry: dict[str, Any]) -> set[str]:
    """The receivers an adapter spells: the scope it registers in, and its slots'.

    Children compose through ``childrenIn``, which takes any receiver unnamed.
    """
    slots = entry.get("slots", {}).values()
    named = {entry.get("scope"), *(slot.get("provides") for slot in slots)}
    return {scope for scope in named if scope is not None}


def render_file(registry: dict[str, Any]) -> str:
    """Render every mechanically-derivable adapter as one Kotlin object.

    Args:
        registry: The parsed schema.

    Returns:
        The generated source, never empty -- the builtins call ``register``
        unconditionally, so the object exists even when nothing qualifies.
    """
    blocks: list[str] = []
    imports: set[str] = set()
    opt_ins: set[str] = set()
    for name in sorted(registry["components"]):
        entry = registry["components"][name]
        block = render(name, entry)
        if block:
            blocks.append(block)
            opt_ins.update(entry.get("optIn", ()))
            package = entry["package"]
            native = native_name(name, entry)
            scopes = _scopes(entry)
            if (entry.get("source") or {}).get("owner") != entry.get("scope"):
                # A member of its scope is called on the receiver, never imported.
                imports.add(f"import {package}.{native}")
            imports.update(f"import {scope}" for scope in scopes)
            for extra in composables(native, entry):
                imports.add(f"import {package}.{extra}")
            for qualified in extra_imports(entry):
                imports.add(f"import {qualified}")
            imports.add(f"import com.pycompose.ir.generated.{name} as {name}Node")

    header = [
        "// Generated by tools/schema/gen.py from schema/catalog.lock.json.",
        "// Do not edit: change the schema and regenerate.",
    ]
    if opt_ins:
        # The pinned declaration requires these markers, and the adapters are one
        # anonymous builder inside one file, so the file declares them.
        header.append(
            "@file:OptIn("
            + ", ".join(f"{marker}::class" for marker in sorted(opt_ins))
            + ")"
        )
    header += [
        "package com.pycompose.host.ui",
        "",
        "import com.pycompose.renderer.ComponentRegistry",
        "import kotlinx.serialization.json.JsonPrimitive",
    ]
    body = [
        "",
        "/** Adapters derived mechanically from the schema, for every component whose",
        " * props carry no decision a generator cannot make. */",
        "object GeneratedAdapters {",
        "    private fun ComponentRegistry.Builder.generated():",
        "        ComponentRegistry.Builder =",
        "        this",
        *blocks,
        "    fun register(into: ComponentRegistry.Builder):",
        "        ComponentRegistry.Builder =",
        "        into.generated()",
        "}",
    ]
    return "\n".join([*header, *sorted(imports), *body]) + "\n"
