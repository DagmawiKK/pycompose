"""Generate the Kotlin adapters that are mechanically derivable.

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

from pycompose.schema.codegen.adapter_calls import (
    _callback,
    _decoded,
    _interaction,
    _named_slot,
    _render_provider,
    _render_value,
    _resolve_constructor,
    _slot_body,
    _state,
    _transient,
)
from pycompose.schema.codegen.adapter_helpers import (
    DECODED,
    GATED_STATES,
    KOTLIN_TYPES,
    MECHANICAL,
    RESOLVER_FALLBACK,
    RESOLVER_RETURN,
    SCALAR_KOTLIN,
    STATE_ATTACH_GATES,
    STATE_CALLS,
    STATE_CONSTRUCTOR_PROPS,
    TRANSIENT_CALLS,
    _camel,
    _Fragments,
    _slot,
    is_mechanical,
    scalar_wire,
)

__all__ = [
    "DECODED",
    "GATED_STATES",
    "KOTLIN_TYPES",
    "MECHANICAL",
    "RESOLVER_FALLBACK",
    "RESOLVER_RETURN",
    "SCALAR_KOTLIN",
    "STATE_ATTACH_GATES",
    "STATE_CALLS",
    "STATE_CONSTRUCTOR_PROPS",
    "TRANSIENT_CALLS",
    "composables",
    "extra_imports",
    "is_mechanical",
    "render",
    "render_file",
]


def composables(name: str, entry: dict[str, Any]) -> set[str]:
    """List the Compose imports one adapter needs beyond the component itself.

    A flattened content slot is its own dependency: ``Button`` compiles without
    ``Text`` in scope until the slot becomes a real ``Text`` call.

    Args:
        name: The component's schema name.
        entry: Its schema entry.

    Returns:
        Simple class names the generated code references, excluding ``name``.
    """
    used = {
        slot["composable"]
        for spec in entry.get("props", {}).values()
        if (slot := spec.get("content")) is not None
    }
    used.discard(name)
    return used


def extra_imports(entry: dict[str, Any]) -> set[str]:
    """List the fully qualified imports an adapter needs beyond its component.

    Args:
        entry: The component's schema entry.

    Returns:
        Import statements' targets, sorted by the caller.
    """
    qualified: set[str] = set()
    for spec in entry.get("props", {}).values():
        if spec.get("type") == "color" and "valueType" in spec:
            qualified.add("kotlinx.serialization.json.JsonObject")
        if spec.get("type") == "dp":
            # Kotlin's own conversion is an extension property, so the import
            # is what makes ``model.props.x.dp`` resolve.
            qualified.add("androidx.compose.ui.unit.dp")
    state = entry.get("state")
    if state is not None:
        qualified.add(f"com.pycompose.renderer.{STATE_CALLS[state['kind']]}")
    if state is not None and state["kind"] in STATE_ATTACH_GATES:
        # The holder rides the component's modifier, so the extension making
        # that ride callable must be imported where the call is written.
        qualified.add("com.pycompose.renderer.attachTo")
    transient = entry.get("transient")
    if transient is not None:
        qualified.add(f"com.pycompose.renderer.{TRANSIENT_CALLS[transient['kind']]}")
    slots = [entry.get("children", {}), *entry.get("slots", {}).values()]
    for slot in slots:
        if slot.get("consume") == "paddingValues":
            qualified.update(
                {
                    "androidx.compose.foundation.layout.Column",
                    "androidx.compose.foundation.layout.padding",
                    "androidx.compose.ui.Modifier",
                }
            )
    if entry.get("children", {}).get("kind") == "items":
        # The primary children are the unslotted ones, and an extension becomes
        # callable only where it is imported.
        qualified.update(
            {
                "androidx.compose.foundation.lazy.items",
                "com.pycompose.renderer.unslotted",
            }
        )
    if any(slot.get("kind") == "items" for slot in entry.get("slots", {}).values()):
        qualified.update(
            {
                "androidx.compose.foundation.lazy.items",
                "com.pycompose.renderer.inSlot",
            }
        )
    return qualified


def _render_dp(prop_name: str, spec: dict[str, Any], out: _Fragments) -> bool:
    """Render a dp prop through Kotlin's own ``Double.dp`` conversion.

    A dp prop rides the wire as a plain finite number; the number already means
    the density-independent unit, so no decoder sits between them. Absence is
    the interesting half: the model cannot hold a ``Dp``, so an optional prop
    names its pinned default in ``nativeDefault`` and the adapter chooses, with
    the native side owning the value it declared.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.
        out: Collects the rendered pieces.

    Returns:
        True when the prop rendered; False leaves the adapter to the hands.
    """
    wire = f"model.props.{prop_name}"
    if spec.get("required") or "default" in spec:
        out.arguments.append(f"{prop_name} = {wire}.dp")
        return True
    if "nativeDefault" in spec:
        # Through a local: the model lives in another module, so its nullable
        # property does not smart-cast.
        out.locals.append(f"val {prop_name}Wire = {wire}")
        out.locals.append(
            f"val {prop_name}Value = if ({prop_name}Wire != null) "
            f"{prop_name}Wire.dp else {spec['nativeDefault']}"
        )
        out.arguments.append(f"{prop_name} = {prop_name}Value")
        return True
    return False


def _render_prop(prop: str, spec: dict[str, Any], out: _Fragments) -> bool:
    """Render one prop into `out`, or report that the adapter cannot be built.

    Args:
        prop: The prop's schema name.
        spec: Its schema entry.
        out: Collects the rendered pieces.

    Returns:
        False when the prop carries a decision a generator cannot make.
    """
    prop_type = spec["type"]
    prop_name = _camel(prop)
    if prop_type == "modifier":
        return True
    if "provider" in spec:
        emitted = _render_provider(prop_name, spec, spec["provider"], out)
    elif prop_type == "value":
        emitted = _render_value(prop_name, spec, out)
    elif spec.get("decode") is not None:
        emitted = out.add(_decoded(prop_name, spec, spec["decode"]))
    elif spec.get("content") is not None:
        emitted = _render_slot(prop_name, spec, out)
    elif prop_type == "actionId":
        callback = _callback(prop_name, spec)
        emitted = callback is not None and out.add(("", callback))
    elif prop_type == "dp":
        emitted = _render_dp(prop_name, spec, out)
    else:
        emitted = _render_scalar(prop_name, spec, out)
    return emitted


def _render_slot(prop_name: str, spec: dict[str, Any], out: _Fragments) -> bool:
    """Render a flattened content slot.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.
        out: Collects the rendered pieces.

    Returns:
        False when the slot is optional and would need a null check.
    """
    slot = _slot(prop_name, spec)
    if slot is None:
        return False
    argument, body = slot
    if argument:
        out.arguments.append(argument)
    out.trailing_lambda(body)
    return True


def _render_scalar(prop_name: str, spec: dict[str, Any], out: _Fragments) -> bool:
    """Render a plain scalar prop, or refuse an undecodable one.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.
        out: Collects the rendered pieces.

    Returns:
        False when the prop's type has no Kotlin mapping this generator knows.
    """
    if spec["type"] not in SCALAR_KOTLIN:
        # An enum, color or resource with no decode. Refused rather than
        # guessed: the value set does not say which resolver family it is.
        return False
    if spec.get("required") or "default" in spec:
        # A nullable property would not compile where Compose wants a value.
        out.arguments.append(f"{prop_name} = {scalar_wire(prop_name, spec)}")
    return True


def _held(state: dict[str, Any] | None) -> set[str]:
    """Return every prop a state declaration keeps from the native arguments.

    The desired value and its report reach the holder, not the component, and
    so does anything else the family holds: props the holder is constructed
    from, and the boolean prop gating an attach through the modifier.

    Args:
        state: The component's raw ``state`` entry, or None.

    Returns:
        The prop names the adapter must not render as native arguments.
    """
    if state is None:
        return set()
    held = {state["value"], state["report"]}
    held.update(STATE_CONSTRUCTOR_PROPS.get(state["kind"], ()))
    gate = STATE_ATTACH_GATES.get(state["kind"])
    if gate is not None:
        held.add(gate)
    return held


def _host_locals(entry: dict[str, Any], out: _Fragments) -> str | None:
    """Emit the locals that fill a component's host-owned parameters.

    The renderer remembers a node's interaction source, its state holder and
    the last serial it fulfilled; the locals fetch them and the arguments
    consume them where the schema says. An attach family fills no parameter of
    its own: its holder rides the modifier, rewritten into the component's
    first argument behind the prop the app states.

    Args:
        entry: The component's schema entry.
        out: The call fragments to extend.

    Returns:
        The expression gating the call for a composition-gated family, or
        None when the component is always composed.
    """
    interaction = entry.get("interaction") or {}
    observed = set((interaction.get("observations") or {}).values())
    state = entry.get("state")
    transient = entry.get("transient")
    if observed:
        out.locals.append(_interaction(interaction))
        out.arguments.append(f"{interaction['native']} = interactionSourceValue")
    gate: str | None = None
    if state is not None:
        local, arguments, gate = _state(state, entry.get("props", {}))
        out.locals.append(local)
        out.arguments.extend(arguments)
        attach = STATE_ATTACH_GATES.get(state["kind"])
        if attach is not None:
            # The holder rides the modifier: the component's first argument is
            # the attach itself, gated by the prop the app states.
            out.arguments[0] = (
                f"modifier = {state['native']}Value.attachTo("
                f"modifier, model.props.{_camel(attach)})"
            )
    if transient is not None:
        out.locals.append(_transient(transient, entry.get("props", {})))
        out.arguments.append(f"{transient['native']} = {transient['native']}Value")
    return gate


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

    out = _Fragments()
    out.arguments.append("modifier = modifier")
    interaction = entry.get("interaction") or {}
    observed = set((interaction.get("observations") or {}).values())
    state = entry.get("state")
    transient = entry.get("transient")
    held = _held(state)
    if transient is not None:
        # Every prop of a transient component is a request input the host
        # consumes on its behalf; none names a native parameter of its own.
        held |= set(entry.get("props", {}))
    if not _resolve_constructor(state, entry.get("props", {}), out):
        return ""
    for prop, spec in entry.get("props", {}).items():
        if prop in observed or prop in held:
            # The host fills the source or the state holder; an observed prop
            # reports state and a held prop carries the app's desired state,
            # but neither names a native parameter of its own.
            continue
        if not _render_prop(prop, spec, out):
            return ""
    gate = _host_locals(entry, out)
    for slot_name, slot in sorted(entry.get("slots", {}).items()):
        out.arguments.append(_named_slot(slot_name, slot))

    children = entry.get("children", {})
    if children.get("allowed"):
        # Emitted by name rather than trailing: the schema says which parameter
        # the primary children reach, and says nothing about where it sits.
        children_body, parameter = _slot_body(
            "model.children",
            None,
            children.get("kind"),
            children.get("consume"),
            children.get("provides"),
        )
        prefix = f"{parameter} -> " if parameter is not None else ""
        native = children.get("native", "content")
        out.arguments.append(f"{native} = {{ {prefix}{children_body} }}")

    indent = "                "
    if gate is not None:
        indent += "    "
    body = "\n".join(f"{indent}    {argument}," for argument in out.arguments)
    tail = ""
    if out.trailing:
        head = " {"
        if out.trailing_parameter is not None:
            head = f" {{ {out.trailing_parameter} ->"
        body_lines = "\n".join(f"{indent}    {line}" for line in out.trailing)
        tail = head + "\n" + body_lines + "\n" + indent + "}"
    node = f"{name}Node"
    prelude = "\n".join(f"                {line}" for line in out.locals)
    call = f"{indent}{name}(\n{body}\n{indent}){tail}"
    if gate is not None:
        # The holder stays outside the gate: the state must outlive the
        # composition of the component it projects.
        call = f"                if ({gate}) {{\n{call}\n                }}"
    scope = entry.get("scope")
    registration = (
        f"register{scope.removesuffix('Scope')}Scoped" if scope else "register"
    )
    return (
        f'            .{registration}("{name}") {{ node, modifier, context ->\n'
        f"                val model = node as {node}\n"
        + (f"{prelude}\n" if prelude else "")
        + f"{call}\n"
        f"            }}"
    )


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
            imports.add(f"import {package}.{name}")
            for extra in composables(name, entry):
                imports.add(f"import {package}.{extra}")
            for qualified in extra_imports(entry):
                imports.add(f"import {qualified}")
            imports.add(f"import com.pycompose.ir.generated.{name} as {name}Node")

    header = [
        "// Generated by tools/schema/gen.py from schema/components.json.",
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
