"""Adapter call builders: one prop's render into call-site fragments.

Each function here turns one parsed prop shape into the Kotlin argument
fragment fragments the composer glues into a generated adapter's call. They
consume only the pin tables and helpers of ``adapter_helpers``; whole-adapter
assembly lives in ``adapters``.
"""

from __future__ import annotations

from typing import Any

from pycompose.schema.codegen.adapter_helpers import (
    GATED_STATES,
    NUMERIC_CONVERSIONS,
    NUMERIC_KOTLIN,
    RESOLVER_FALLBACK,
    RESOLVER_OWNER,
    RESOLVER_RETURN,
    SCALAR_KOTLIN,
    STATE_ATTACH_GATES,
    STATE_CONSTRUCTOR_PROPS,
    _camel,
    _Fragments,
    qualify,
    state_call,
)
from pycompose.schema.codegen.values import resolver_call


def _provided(expression: str, wire: str | None, target: str) -> str | None:
    """Coerce a resolved value to a provider's pinned return type.

    ``wire`` is the Kotlin type the generator resolved the prop into, or None
    when that type is a family resolver's contract: the compiler checks the
    lambda against the pinned parameter and composegen's check verifies ``target``
    against the pin, so no coercion is invented there.

    Args:
        expression: The Kotlin expression holding the resolved value.
        wire: The Kotlin type of that expression, when the generator knows it.
        target: The provider's ``returns`` type.

    Returns:
        The coerced expression, or None when the pair has no stated conversion.
    """
    if wire is None or wire == target:
        return expression
    if wire in NUMERIC_KOTLIN and target in NUMERIC_KOTLIN:
        conversion = NUMERIC_CONVERSIONS.get((wire, target))
        return None if conversion is None else f"{expression}.{conversion}()"
    return None


def _render_provider(
    prop_name: str, spec: dict[str, Any], provider: dict[str, Any], out: _Fragments
) -> bool:
    """Render a prop the native call receives as a zero-arg lambda.

    The app states a value in the snapshot, and the host reads it during
    composition to supply the lambda the native parameter declares. Python is
    never called from composition, and the parameter stays a value the app
    cannot name: the schema requires the prop, so the adapter has exactly one
    call shape.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.
        provider: Its validated ``provider`` object.
        out: Collects the rendered pieces.

    Returns:
        False when the prop's type cannot be resolved, or the resolved type has
        no stated conversion to the pinned return type.
    """
    local: str
    wire: str | None
    if spec["type"] == "value":
        wire = None
        local = (
            f"val {prop_name}Value = "
            f"{resolver_call(spec['valueType'], f'model.props.{prop_name}')}"
            ".getOrThrow()"
        )
    elif spec.get("decode") is not None:
        decoded = _decoded(prop_name, spec, spec["decode"])
        if decoded is None:
            return False
        local, _ = decoded
        wire = RESOLVER_RETURN.get(spec["decode"])
    elif spec["type"] in SCALAR_KOTLIN:
        wire = SCALAR_KOTLIN[spec["type"]]
        local = f"val {prop_name}Value = model.props.{prop_name}"
    else:
        return False
    argument = _provided(f"{prop_name}Value", wire, provider["returns"])
    if argument is None:
        return False
    return out.add((local, f"{provider['native']} = {{ {argument} }}"))


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

    resolver = qualify(RESOLVER_OWNER.get(decoder, "PropResolver"))

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
    # An optional callback's action id is nullable: a call the app did not bind
    # reaches nobody, and the native default behaviour stays in charge.
    action = f"model.props.{prop_name}" if spec.get("required") else "it"
    bound = "" if spec.get("required") else f"model.props.{prop_name}?.let {{ "
    close = "" if spec.get("required") else " }"
    if not payload:
        return f"{prop_name} = {{ {bound}context.actions.dispatch({action}){close} }}"
    if len(payload) != 1:
        return None
    field_name, kind = payload[0]["name"], payload[0]["type"]
    if kind not in SCALAR_KOTLIN:
        return None
    return (
        f"{prop_name} = {{ {field_name} -> "
        f"{bound}context.event({action}, JsonPrimitive({field_name})){close} }}"
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
    # Nothing observing yields no source; a component whose parameter is
    # non-null then gets the one it would have remembered itself.
    return (
        "val interactionSourceValue = context.interactionSource("
        f"model.id, mapOf({entries})) ?: androidx.compose.runtime.remember "
        "{ androidx.compose.foundation.interaction.MutableInteractionSource() }"
    )


def _state(
    state: dict[str, Any], props: dict[str, Any]
) -> tuple[str, list[str], str | None]:
    """Render the local that fetches one component's host-owned state holder.

    The holder is the renderer's, remembered per node id; the desired value and
    the report channel are ordinary props, so the app keeps naming its own
    fields and the host never holds a Python object. Props the holder is
    constructed from reach the renderer's call too, resolved where the ordinary
    value props are resolved.

    Args:
        state: The component's raw ``state`` entry.
        props: The component's declared props, by wire name.

    Returns:
        The Kotlin local declaration, the native arguments consuming it, and the
        expression gating the call for a family that must be composed
        conditionally, or None when the component is always composed.
    """
    native = state["native"]
    held = f"{native}Value"
    value = _camel(state["value"])
    report = _camel(state["report"])
    gated = state["kind"] in GATED_STATES
    # An attach family fills no parameter: its holder rides the modifier the
    # composer rewrites, and the component is composed unconditionally.
    attached = state["kind"] in STATE_ATTACH_GATES
    arguments = (
        []
        if attached
        else [f"{native} = {held}.state" if gated else f"{native} = {held}"]
    )
    # Props the holder is constructed from also reach the renderer's call; the
    # renderer resolves each against the holder's constructor, so a value-typed
    # one arrives as its resolved local and never as raw tagged data.
    extras = "".join(
        f", {_constructor_argument(name, props.get(name) or {})}"
        for name in STATE_CONSTRUCTOR_PROPS.get(state["kind"], ())
    )
    dismiss = state.get("dismiss")
    if dismiss is not None:
        # The component announces a dismissal it has already carried out; the
        # settled change reports through the report prop, so the callback is
        # answered with nothing rather than with a second channel.
        arguments.append(f"{dismiss} = {{}}")
    return (
        f"val {held} = context.{state_call(state['kind'])}("
        f"model.props.{value}, model.props.{report}{extras})",
        arguments,
        f"{held}.visible" if gated else None,
    )


def _constructor_argument(name: str, spec: dict[str, Any]) -> str:
    """The Kotlin expression a holder's constructor prop arrives as.

    A value-typed prop crosses as tagged data and is resolved into a local
    before this point; every other prop crosses as the model's own property.

    Args:
        name: The prop's schema name.
        spec: Its schema entry.

    Returns:
        The expression the renderer's call names.
    """
    prop = _camel(name)
    if spec.get("type") == "value" and "valueType" in spec:
        return f"{prop}Value"
    return f"model.props.{prop}"


def _render_value(prop_name: str, spec: dict[str, Any], out: _Fragments) -> bool:
    """Render a prop carrying a native value-family tag.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.
        out: Collects the rendered pieces.

    Returns:
        True when the value could be resolved into a local.
    """
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


def _resolve_constructor(
    state: dict[str, Any] | None,
    props: dict[str, Any],
    out: _Fragments,
) -> bool:
    """Resolve the value-typed props a holder is constructed from, into locals.

    A constructor prop reaches the holder, never the component, so the ordinary
    prop loop leaves it out -- but a value-typed one still crosses as tagged
    data and needs the same resolver every other value prop gets. Only the
    local is emitted: the holder's call names it, the component never does.

    Args:
        state: The component's raw ``state`` entry, or None.
        props: The component's declared props, by wire name.
        out: Collects the rendered pieces.

    Returns:
        False when one of the props cannot be resolved faithfully.
    """
    if state is None:
        return True
    for name in STATE_CONSTRUCTOR_PROPS.get(state["kind"], ()):
        spec = props.get(name) or {}
        if spec.get("type") != "value" or "valueType" not in spec:
            continue
        resolved = _Fragments()
        if not _render_value(_camel(name), spec, resolved):
            return False
        out.locals.extend(resolved.locals)
    return True


def _transient(transient: dict[str, Any], props: dict[str, Any]) -> str:
    """Render the local that requests one component's host-fulfilled transient.

    Every prop is a request input the host consumes on the holder's behalf --
    the serial it compares, the message it shows, the occurrence it answers --
    so they all reach the renderer's context call by name, under the node's
    identity, and none reaches the component itself. The component's modifier
    is the exception: it is not a request but the call's own first argument,
    built and passed by the adapter like anywhere else.

    Args:
        transient: The component's raw ``transient`` entry.
        props: The component's declared props, by wire name.

    Returns:
        The Kotlin local declaration.
    """
    entries = ", ".join(
        f"{name} = model.props.{_camel(name)}"
        for name in sorted(props)
        if name != "modifier"
    )
    call = transient["kind"]
    return f"val {transient['native']}Value = context.{call}(model.id, {entries})"


def _slot_body(
    nodes: str,
    name: str | None,
    kind: str | None,
    consume: str | None,
    provides: str | None = None,
) -> tuple[str, str | None]:
    """Render the inside of one declared slot's content lambda.

    Args:
        nodes: Kotlin expression for the parent's child list.
        name: Slot name, or None for the primary children.
        kind: ``content`` composes nodes in order; ``items`` lists them lazily.
        consume: Slot scope the adapter consumes on the subtree's behalf.
        provides: Composition scope the pinned lambda carries, handed to the
            children so a scoped child composes under its provider.

    Returns:
        The lambda body, then its parameter name when the slot consumes a scope.
    """
    if kind == "items" and name is None:
        # The primary children may be a window of a longer list (ADR-0043).
        read = (
            f"windowedItems(context, {nodes}.unslotted(), "
            "model.props.itemCount, model.props.itemOffset)"
        )
    elif kind == "items":
        listed = f'{nodes}.inSlot("{name}")'
        read = f"items({listed}, key = {{ it.id }}) {{ context.node(it) }}"
    elif name is None:
        read = (
            f"context.childrenIn{provides}(this, {nodes})"
            if provides is not None and consume is None
            else f"context.children({nodes})"
        )
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
    provides = slot.get("provides")
    if provides is not None:
        # The native lambda carries the receiver, so the slot renderer hands
        # that same receiver to scoped children.  A non-null parameter still
        # needs a lambda when the format is empty; the empty lambda preserves
        # the native default.
        call = f'context.slotIn{provides}(model.children, "{slot_name}")'
        if slot.get("nullable"):
            return f"{native} = {call}"
        return f"{native} = {call} ?: {{}}"
    if slot.get("nullable") and consume is None:
        return f'{native} = context.slot(model.children, "{slot_name}")'
    body, parameter = _slot_body("model.children", slot_name, kind, consume)
    prefix = f"{parameter} -> " if parameter is not None else ""
    return f"{native} = {{ {prefix}{body} }}"
