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

from pycompose.schema.codegen.values import resolver_call

COMPOSE_PACKAGE = {
    "Box": "androidx.compose.foundation.layout",
    "Button": "androidx.compose.material3",
    "Checkbox": "androidx.compose.material3",
    "Column": "androidx.compose.foundation.layout",
    "DismissibleNavigationDrawer": "androidx.compose.material3",
    "FilterChip": "androidx.compose.material3",
    "Image": "androidx.compose.foundation",
    "LazyColumn": "androidx.compose.foundation.lazy",
    "ModalNavigationDrawer": "androidx.compose.material3",
    "Row": "androidx.compose.foundation.layout",
    "Scaffold": "androidx.compose.material3",
    "Spacer": "androidx.compose.foundation.layout",
    "Text": "androidx.compose.material3",
    "TextButton": "androidx.compose.material3",
    "TextField": "androidx.compose.material3",
}
"""Where each component's Compose class lives.

Placeholder knowledge, and the only part of this file that is not derived from the
schema. Phase C removes it: the API dump already says which ``*Kt`` class each
composable hangs off, so the package is derivable rather than listed.
"""

SCALAR_KOTLIN = {
    "string": "String",
    "boolean": "Boolean",
    "integer": "Long",
    "number": "Double",
}

DECODED = {"enum", "color", "resource"}
"""Prop types that arrive on the wire as something other than their Kotlin type."""

RESOLVER_RETURN = {
    "alignment": "Alignment",
    "arrangement": "Arrangement.Vertical",
    "color": "Color",
    "horizontal": "Alignment.Horizontal",
    "resourceFont": "FontFamily?",
    "resourceImage": "Painter?",
    "resourceText": "String?",
    "textStyle": "TextStyle",
    "vertical": "Alignment.Vertical",
}
"""What each decoder hands back.

Needed because a prop's Kotlin type is not its wire type: the wire carries the
string ``"start"`` and Compose wants an ``Alignment.Horizontal``. The schema's
``decode`` names the resolver; this says what comes out of it, so a generated
adapter can declare the local it assigns to.
"""

RESOLVER_FALLBACK = {
    "alignment": "Alignment.TopStart",
    "arrangement": "Arrangement.Top",
    "color": "Color.Unspecified",
    "horizontal": "Alignment.Start",
    "resourceFont": "null",
    "resourceImage": "null",
    "resourceText": "null",
    "textStyle": "MaterialTheme.typography.bodyMedium",
    "vertical": "Alignment.Top",
}
"""What a malformed value falls back to.

Degrade, never throw: Compose must not see an exception from a bad prop in a
debug snapshot (ADR-0005). Each is the value the hand-written adapter already
chose for the same prop, so generating does not change behaviour.
"""

SLOT_KINDS = frozenset({"content", "items"})
"""How a slot composes: nodes in order, or lazy list items with stable keys."""

CONSUMERS = frozenset({"paddingValues"})
"""Slot scopes the adapter consumes, so an app never double-applies one."""

KOTLIN_TYPES = {
    "Alignment": "androidx.compose.ui.Alignment",
    "Arrangement": "androidx.compose.foundation.layout.Arrangement",
    "Color": "androidx.compose.ui.graphics.Color",
    "FontFamily": "androidx.compose.ui.text.font.FontFamily",
    "MaterialTheme": "androidx.compose.material3.MaterialTheme",
    "Painter": "androidx.compose.ui.graphics.painter.Painter",
    "PropResolver": "com.pycompose.renderer.PropResolver",
    "TextStyle": "androidx.compose.ui.text.TextStyle",
}
"""Package for every bare Compose name this generator emits.

Generated code names resolvers and their returns in full instead of importing
them, the way the value path already did: one less import list to keep honest,
and a name that cannot be shadowed by a prop.
"""

MECHANICAL = {"string", "boolean", "integer", "number", "actionId", "modifier"}
"""Schema prop types an adapter can render with no decision and no decoder.

``color``, ``enum`` and ``resource`` are renderable too, but only when the prop
declares a ``decode``: those types arrive on the wire as strings and need a
resolver to become a ``Color`` or an ``Alignment``. A prop of one of those types
with no ``decode`` is refused, because guessing which family its values belong to
is how an adapter silently renders the wrong alignment.
"""

STATE_CALLS = {"drawer": "drawerState"}
"""The renderer method each state family's host holder comes from.

The family decides the create/drive/report logic; the schema decides which
component has one, which native parameter it fills, and which props carry the
desired value and report settled changes. Every member of the vocabulary must
appear here, or codegen has no holder to hand the component.
"""


def qualify(source: str) -> str:
    """Fully qualify a Kotlin expression's leading type name.

    Args:
        source: Kotlin source, e.g. ``Arrangement.Vertical`` or ``Color?``.

    Returns:
        The source with a known leading type name replaced by its package-qualified
        spelling; anything already qualified or unknown is returned unchanged.
    """
    head, separator, rest = source.partition(".")
    nullable = head.endswith("?")
    bare = head[:-1] if nullable else head
    qualified = KOTLIN_TYPES.get(bare)
    if qualified is None:
        return source
    return f"{qualified}{'?' if nullable else ''}{separator}{rest}"


def _camel(name: str) -> str:
    """Return a snake_case wire name as camelCase.

    Args:
        name: The schema's prop name.

    Returns:
        The Kotlin property name.
    """
    head, *rest = name.split("_")
    return head + "".join(word[:1].upper() + word[1:] for word in rest)


def _declared_slots(entry: dict[str, Any]) -> bool:
    """Report whether every child path is drawn from the closed slot vocabulary.

    Args:
        entry: The component's schema entry.

    Returns:
        True when the primary children and every named slot use a kind and a
        consumer this generator renders.
    """
    children = entry.get("children", {})
    if children.get("kind") not in {None, *SLOT_KINDS}:
        return False
    if children.get("consume") not in {None, *CONSUMERS}:
        return False
    for slot in entry.get("slots", {}).values():
        if slot.get("kind", "content") not in SLOT_KINDS:
            return False
        if slot.get("consume") not in {None, *CONSUMERS}:
            return False
    return True


def is_mechanical(entry: dict[str, Any]) -> bool:
    """Report whether a component's adapter can be derived from its schema.

    Args:
        entry: The component's schema entry.

    Returns:
        True when every prop renders without a human decision.
    """
    if entry.get("adapter") == "manual":
        return False
    if entry.get("wrapper"):
        # Text and Image hand off to ResourceText / ResourceImage, which load
        # their content off the Compose thread and report their own diagnostics.
        # The call site is mechanical; what it delegates to is not.
        return False
    if not _declared_slots(entry):
        return False
    for spec in entry.get("props", {}).values():
        if "valueType" in spec:
            if spec["type"] == "value" and (
                spec.get("required") or "nativeDefault" in spec
            ):
                continue
            # A colour prop takes a tagged value *or* the legacy string, and the
            # adapter handles both explicitly; no other decoded family does.
            if spec.get("type") == "color" and spec.get("decode") == "color":
                continue
            return False
        if spec.get("type") in MECHANICAL:
            continue
        # Decodable types need a named resolver; without one they cannot be
        # rendered at all rather than rendered wrongly.
        if spec.get("type") in DECODED and spec.get("decode"):
            continue
        return False
    return True


def _slot(prop_name: str, spec: dict[str, Any]) -> tuple[str, str] | None:
    """Render a prop flattened out of a Compose content slot.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.

    Returns:
        ``(argument, trailing)`` where either may be empty, or None when the
        slot is optional and would need a null check -- a decision, not a
        derivation.
    """
    slot = spec.get("content")
    if slot is None:
        return None
    if not spec.get("required"):
        return None
    wrapped = f"{slot['composable']}(model.props.{prop_name})"
    parameter = slot.get("parameter")
    if parameter is not None:
        return f"{parameter} = {{ {wrapped} }}", ""
    return "", wrapped


def _decoded(
    prop_name: str, spec: dict[str, Any], decoder: str
) -> tuple[str, str] | None:
    """Render one enum, color or resource prop through its declared resolver.

    ``PropResolver`` already knows how to turn ``"start"`` into an
    ``Alignment.Horizontal``; what it could not know was *which* family a given
    prop's values belonged to. That is what the schema's ``decode`` field says
    now, so this emits a call rather than guessing.

    The result is bound to a local rather than inlined because a resolver call
    inside an argument list runs a lambda, and Compose composable parameters
    (``textStyle`` reads ``MaterialTheme``) are only legal in a composable
    scope -- not inside a nested argument expression.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.
        decoder: The resolver the schema named.

    Returns:
        A ``(local declaration, argument)`` pair, or ``(None, "")`` when the
        prop cannot be rendered.
    """
    declared = RESOLVER_RETURN.get(decoder)
    # A declared fallback wins: it is the value the hand-written adapter used for
    # exactly this parameter, and a per-decoder default is a guess about the rest.
    declared_fallback = spec.get("fallback") or RESOLVER_FALLBACK.get(decoder)
    if declared is None or declared_fallback is None:
        return None
    returns = qualify(declared)
    fallback = qualify(declared_fallback)

    # An optional prop is nullable in the model, so an absent value must not
    # reach a resolver that takes a non-null String.
    optional = not spec.get("required") and "default" not in spec
    wire = f"model.props.{prop_name}"
    access = f"{wire}?.takeIf {{ it.isNotEmpty() }}" if optional else wire
    value = f"{prop_name}Value"

    resolver = qualify("PropResolver")

    if decoder.startswith("resource"):
        # A resource reference is a single wire string naming a kind and a name
        # ("@drawable/ic_note"), so it goes through the resolver method that
        # takes the whole reference rather than one taking a bare name. An
        # absent resolver means the app declared no resources at all.
        # decoder "resourceImage" -> ResourceResolver.image(reference). The
        # name is lowerCamel on both sides; lowercasing the whole thing would
        # have produced `resources?.Image(...)` and a compiler error.
        method = decoder[len("resource") :][0].lower() + decoder[len("resource") + 1 :]
        # Every resource accessor returns a Result, and a bad reference must not
        # escape into Compose -- ADR-0005's degrade-don't-throw rule.
        call = f"resources?.{method}({wire}).getOrNull()"
        return f"val {value}: {returns} = {call}", f"{prop_name} = {value}"

    if decoder == "color" and "valueType" in spec:
        # The wire carries either a tagged value (the app built a Color) or a
        # legacy string, exactly as the hand-written helper read it. Tagged
        # first: it is the form that could carry a theme reference.
        tagged = resolver_call(spec["valueType"], "wire")
        return (
            f"val {value}: {returns} = when (val wire = {wire}) {{\n"
            f"                    is JsonObject -> {tagged}.getOrDefault({fallback})\n"
            "                    is JsonPrimitive -> "
            f"{resolver}.color(wire.content).getOrDefault({fallback})\n"
            f"                    else -> {fallback}\n"
            "                }",
            f"{prop_name} = {value}",
        )

    if decoder == "textStyle":
        # The adapter body is already composable, so a plain local is enough;
        # the resolver itself is what must run in composition.
        return (
            f"val {value}: {returns} = {resolver}" f".textStyle({access}, {fallback})",
            f"{prop_name} = {value}",
        )
    resolved = f"{resolver}.{decoder}({access}).getOrDefault({fallback})"
    return f"val {value}: {returns} = {resolved}", f"{prop_name} = {value}"


def _callback(prop_name: str, spec: dict[str, Any]) -> str | None:
    """Render one actionId prop as a Kotlin callback argument.

    Compose's ``onClick`` takes nothing and dispatches the bare actionId, while
    ``onCheckedChange`` hands back the new value and reports it alongside. Which
    of the two a callback is used to be invisible from the component entry; the
    schema's ``payload`` says so since 1.9.0, and guessing produces a callback
    with the wrong arity.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.

    Returns:
        The argument, or None when the callback shape is one this cannot render.
    """
    payload = spec.get("payload")
    if not payload:
        return f"{prop_name} = {{ context.actions.dispatch(model.props.{prop_name}) }}"
    if len(payload) != 1:
        return None
    field_name, kind = payload[0]["name"], payload[0]["type"]
    if kind not in SCALAR_KOTLIN:
        return None
    return (
        f"{prop_name} = {{ {field_name} -> "
        f"context.event(model.props.{prop_name}, JsonPrimitive({field_name})) }}"
    )


def _interaction(interaction: dict[str, Any]) -> str:
    """Render the local that fetches one component's host-created source.

    The source is the renderer's, remembered per node id; which payload field
    each observation fills is resolved against the app's binding at dispatch
    time, the same way every other callback's event field is, so the app keeps
    naming its own fields.

    Args:
        interaction: The component's raw ``interaction`` entry.

    Returns:
        The Kotlin local declaration.
    """
    observations = interaction["observations"]
    entries = ", ".join(
        f'"{kind}" to model.props.{_camel(observations[kind])}'
        for kind in sorted(observations)
    )
    return (
        "val interactionSourceValue = context.interactionSource("
        f"model.id, mapOf({entries}))"
    )


def _state(state: dict[str, Any]) -> tuple[str, str]:
    """Render the local that fetches one component's host-owned state holder.

    The holder is the renderer's, remembered per node id; the desired value and
    the report channel are ordinary props, so the app keeps naming its own
    fields and the host never holds a Python object.

    Args:
        state: The component's raw ``state`` entry.

    Returns:
        The Kotlin local declaration, then the native argument consuming it.
    """
    native = state["native"]
    held = f"{native}Value"
    value = _camel(state["value"])
    report = _camel(state["report"])
    return (
        f"val {held} = context.{STATE_CALLS[state['kind']]}("
        f"model.props.{value}, model.props.{report})",
        f"{native} = {held}",
    )


def _slot_body(
    nodes: str,
    name: str | None,
    kind: str | None,
    consume: str | None,
) -> tuple[str, str | None]:
    """Render the inside of one declared slot's content lambda.

    Args:
        nodes: Kotlin expression for the parent's child list.
        name: Slot name, or None for the primary children.
        kind: ``content`` composes nodes in order; ``items`` lists them lazily.
        consume: Slot scope the adapter consumes on the subtree's behalf.

    Returns:
        The lambda body, then its parameter name when the slot consumes a scope.
    """
    if kind == "items":
        listed = (
            f"context.unslotted({nodes})"
            if name is None
            else f'context.slotNodes({nodes}, "{name}")'
        )
        read = f"items({listed}, key = {{ it.id }}) {{ context.node(it) }}"
    elif name is None:
        read = f"context.children({nodes})"
    else:
        # The parameter is non-null, so the lambda always runs and the slot's
        # own lambda is invoked inside it. Evaluating the slot without invoking
        # it would build the subtree and drop it: a component that renders
        # nothing, which is what this line used to do.
        read = f'context.slot({nodes}, "{name}")?.invoke()'
    if consume is None:
        return read, None
    return f"Column(Modifier.padding(padding)) {{ {read} }}", "padding"


def _named_slot(slot_name: str, slot: dict[str, Any]) -> str:
    """Render one named slot as a Kotlin argument.

    A nullable Compose parameter takes the slot lambda directly, so an empty
    subtree stays ``null`` and keeps Compose's own default -- passing an empty
    lambda to FilterChip's ``leadingIcon`` would reserve icon space for nothing.
    A non-null parameter always gets a lambda and composes nothing when empty.

    Args:
        slot_name: The declared slot name.
        slot: Its schema entry.

    Returns:
        The ``native = ...`` argument.
    """
    native = slot["native"]
    kind = slot.get("kind", "content")
    consume = slot.get("consume")
    if slot.get("nullable") and consume is None:
        return f'{native} = context.slot(model.children, "{slot_name}")'
    body, parameter = _slot_body("model.children", slot_name, kind, consume)
    prefix = f"{parameter} -> " if parameter is not None else ""
    return f"{native} = {{ {prefix}{body} }}"


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
        if slot.get("kind") == "items":
            qualified.add("androidx.compose.foundation.lazy.items")
    return qualified


class _Fragments:
    """The pieces one adapter is assembled from.

    A list of strings was enough until decoded props arrived, which needed three
    positions -- locals before the call, arguments inside it, and a trailing
    content lambda after it -- and a single growing list pushed `render` past
    the branch limit. Naming the three keeps each obvious.
    """

    def __init__(self) -> None:
        """Start empty."""
        self.locals: list[str] = []
        self.arguments: list[str] = []
        self.trailing: list[str] = []
        self.trailing_parameter: str | None = None

    def add(self, fragment: tuple[str, str] | None) -> bool:
        """Append one prop's rendering.

        Args:
            fragment: The local/argument pair, or None to refuse.

        Returns:
            False when the prop cannot be rendered and the adapter is abandoned.
        """
        if fragment is None:
            return False
        local, argument = fragment
        if local:
            self.locals.append(local)
        if argument:
            self.arguments.append(argument)
        return True

    def trailing_lambda(self, body: str, parameter: str | None = None) -> None:
        """Record a content lambda that follows the call.

        Args:
            body: The lambda body, already indented.
            parameter: Lambda parameter name, for a slot that consumes a scope.
        """
        if body:
            self.trailing.append(body)
            self.trailing_parameter = parameter or self.trailing_parameter


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

    if prop_type == "value":
        family = spec["valueType"]
        wire = f"model.props.{prop_name}"
        declaration = ""
        if not spec.get("required"):
            declaration = f"val {prop_name}Wire = {wire}\n                "
            wire = f"{prop_name}Wire"
        call = resolver_call(family, wire) + ".getOrThrow()"
        if spec.get("nullable"):
            call = (
                f"when ({wire}) {{\n"
                "                    com.pycompose.ir.OptionalValue.Absent -> "
                f"{spec['nativeDefault']}\n"
                "                    com.pycompose.ir.OptionalValue.Null -> null\n"
                f"                    is com.pycompose.ir.OptionalValue.Present -> "
                f"{resolver_call(family, f'{wire}.value')}.getOrThrow()\n"
                "                }"
            )
        elif not spec.get("required"):
            call = f"if ({wire} != null) {call} else {spec['nativeDefault']}"
        return out.add(
            (
                f"{declaration}val {prop_name}Value = {call}",
                f"{prop_name} = {prop_name}Value",
            )
        )

    decoder = spec.get("decode")
    if decoder is not None:
        return out.add(_decoded(prop_name, spec, decoder))
    if spec.get("content") is not None:
        return _render_slot(prop_name, spec, out)
    if prop_type == "actionId":
        callback = _callback(prop_name, spec)
        return callback is not None and out.add(("", callback))
    return _render_scalar(prop_name, spec, out)


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
        out.arguments.append(f"{prop_name} = model.props.{prop_name}")
    return True


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
    held = {state["value"], state["report"]} if state else set()
    for prop, spec in entry.get("props", {}).items():
        if prop in observed or prop in held:
            # The host fills the source or the state holder; an observed prop
            # reports state and a held prop carries the app's desired state,
            # but neither names a native parameter of its own.
            continue
        if not _render_prop(prop, spec, out):
            return ""
    if observed:
        out.locals.append(_interaction(interaction))
        out.arguments.append(f"{interaction['native']} = interactionSourceValue")
    if state is not None:
        local, argument = _state(state)
        out.locals.append(local)
        out.arguments.append(argument)
    for slot_name, slot in sorted(entry.get("slots", {}).items()):
        out.arguments.append(_named_slot(slot_name, slot))

    children = entry.get("children", {})
    if children.get("allowed"):
        # Emitted by name rather than trailing: the schema says which parameter
        # the primary children reach, and says nothing about where it sits.
        children_body, parameter = _slot_body(
            "model.children", None, children.get("kind"), children.get("consume")
        )
        prefix = f"{parameter} -> " if parameter is not None else ""
        native = children.get("native", "content")
        out.arguments.append(f"{native} = {{ {prefix}{children_body} }}")

    body = "\n".join(f"                    {argument}," for argument in out.arguments)
    tail = ""
    if out.trailing:
        head = " {"
        if out.trailing_parameter is not None:
            head = f" {{ {out.trailing_parameter} ->"
        body_lines = "\n".join(f"                    {line}" for line in out.trailing)
        tail = head + "\n" + body_lines + "\n                }"
    node = f"{name}Node"
    prelude = "\n".join(f"                {line}" for line in out.locals)
    return (
        f'            .register("{name}") {{ node, modifier, context ->\n'
        f"                val model = node as {node}\n"
        + (f"{prelude}\n" if prelude else "")
        + f"                {name}(\n"
        f"{body}\n"
        f"                ){tail}\n"
        f"            }}"
    )


def render_file(registry: dict[str, Any]) -> str:
    """Render every mechanically-derivable adapter as one Kotlin object.

    Args:
        registry: The parsed schema.

    Returns:
        The generated source, or an empty string when nothing qualifies.
    """
    blocks: list[str] = []
    imports: set[str] = set()
    for name in sorted(registry["components"]):
        entry = registry["components"][name]
        block = render(name, entry)
        if block:
            blocks.append(block)
            package = COMPOSE_PACKAGE.get(name)
            if package is None:
                continue
            imports.add(f"import {package}.{name}")
            for extra in composables(name, entry):
                imports.add(f"import {package}.{extra}")
            for qualified in extra_imports(entry):
                imports.add(f"import {qualified}")
            imports.add(f"import com.pycompose.ir.generated.{name} as {name}Node")
    if not blocks:
        return ""

    header = [
        "// Generated by tools/schema/gen.py from schema/components.json.",
        "// Do not edit: change the schema and regenerate.",
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
