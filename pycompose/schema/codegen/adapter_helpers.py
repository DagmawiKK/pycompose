"""Mechanical adapter layer: pin tables and slot-parsing helpers.

The tables here are the embedding policy a generated adapter follows -- how a
wire type becomes a Kotlin type, which resolvers decode which prop families
and which reserved names the call builder quotes them into. Slot-parsing
predicates decide what a component entry contains; the call builders that turn
a parsed prop into its call-site fragments live in ``adapter_calls``, and the
composer that assembles whole adapters lives in ``adapters``.
"""

from __future__ import annotations

from typing import Any

from pycompose.core.registry_types import CONSUMERS, SCOPES, SLOT_KINDS

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
    "tooltipPosition": "TooltipAnchorPosition",
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
    "tooltipPosition": "TooltipAnchorPosition.Above",
    "vertical": "Alignment.Top",
}
"""What a malformed value falls back to.

Degrade, never throw: Compose must not see an exception from a bad prop in a
debug snapshot (ADR-0005). Each is the value the hand-written adapter already
chose for the same prop, so generating does not change behaviour.
"""

KOTLIN_TYPES = {
    "Alignment": "androidx.compose.ui.Alignment",
    "Arrangement": "androidx.compose.foundation.layout.Arrangement",
    "Color": "androidx.compose.ui.graphics.Color",
    "FontFamily": "androidx.compose.ui.text.font.FontFamily",
    "MaterialTheme": "androidx.compose.material3.MaterialTheme",
    "Painter": "androidx.compose.ui.graphics.painter.Painter",
    "PropResolver": "com.pycompose.renderer.PropResolver",
    "TextStyle": "androidx.compose.ui.text.TextStyle",
    "TooltipAnchorPosition": "androidx.compose.material3.TooltipAnchorPosition",
    "TooltipPropResolver": "com.pycompose.renderer.TooltipPropResolver",
}
"""Package for every bare Compose name this generator emits.

Generated code names resolvers and their returns in full instead of importing
them, the way the value path already did: one less import list to keep honest,
and a name that cannot be shadowed by a prop.
"""

RESOLVER_OWNER = {"tooltipPosition": "TooltipPropResolver"}
"""Specialised native decoders; other non-resource decoders use PropResolver."""

MECHANICAL = {"string", "boolean", "integer", "number", "actionId", "modifier"}
"""Schema prop types an adapter can render with no decision and no decoder.

``color``, ``enum`` and ``resource`` are renderable too, but only when the prop
declares a ``decode``: those types arrive on the wire as strings and need a
resolver to become a ``Color`` or an ``Alignment``. A prop of one of those types
with no ``decode`` is refused, because guessing which family its values belong to
is how an adapter silently renders the wrong alignment.
"""

STATE_CALLS = {
    "drawer": "drawerState",
    "sheet": "sheetState",
    "slider": "sliderState",
    "scroll": "scrollState",
    "lazyList": "lazyListState",
    "tooltip": "tooltipState",
    "textInput": "textInputState",
    "search": "searchState",
    "swipe": "swipeState",
}
"""The renderer method each state family's host holder comes from.

The family decides the create/drive/report logic; the schema decides which
component has one, which native parameter it fills, and which props carry the
desired value and report settled changes. Every member of the vocabulary must
appear here, or codegen has no holder to hand the component.
"""

GATED_STATES = frozenset({"sheet"})
"""State families whose native component must be composed conditionally.

``ModalBottomSheet`` shows itself as soon as it is composed and measured, and a
composed sheet keeps its own window in front of the app even while hidden, so
presence is the only way to show one and absence the only way to let the app
through. A gated family's holder carries the native state in ``state`` and the
composition gate in ``visible``; any other family's holder is the native state
itself.
"""

STATE_CONSTRUCTOR_PROPS = {
    "sheet": ("value", "onValueChange", "skipPartiallyExpanded"),
    "slider": ("valueRange", "steps"),
    "tooltip": ("isPersistent",),
    "textInput": ("selectionStart", "selectionEnd", "revision"),
    "search": ("text", "selectionStart", "selectionEnd", "revision", "onEdit"),
}
"""Props each family's holder needs at construction, beyond its primary projection.

A ``SliderState`` is built from the range and the steps and owns them for as
long as it lives; a tooltip holder is built with its persistence policy. A
sheet carries a second projection beside its boolean presence -- the anchor and
its report -- because one node states both. They flow into the renderer call
that creates the holder rather than into the component's own arguments. Every
prop named here is held exactly as the primary value and report are: the app
states it, the adapter passes it to the holder, and it never reaches the
component.
"""

STATE_ATTACH_GATES = {"scroll": "scrollable"}
"""Props gating a family whose holder rides the call's modifier.

``Column`` has no scroll parameter -- scrolling attaches through its modifier,
so the state cannot fill a native parameter. The holder exists whenever the
schema declares one, and the boolean prop named here decides whether the
adapter attaches it to the modifier the call receives.
"""

TRANSIENT_CALLS = {"snackbar": "snackbar"}
"""The renderer method each transient family's request comes from.

The family decides the remember/fulfil/report logic exactly as a state's
``STATE_CALLS`` entry does; the schema decides which component asks for one.
Every member of the vocabulary must appear here, or codegen has no renderer
method to call.
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
    if any(slot.get("host") for slot in entry.get("slots", {}).values()):
        return False
    children = entry.get("children", {})
    scoped = children.get("provides") in {None, *SCOPES} and not (
        "provides" in children and children.get("consume") is not None
    )
    return (
        children.get("kind") in {None, *SLOT_KINDS}
        and children.get("consume") in {None, *CONSUMERS}
        and scoped
        and all(
            slot.get("kind", "content") in SLOT_KINDS
            and slot.get("consume") in {None, *CONSUMERS}
            and slot.get("provides") in {None, *SCOPES}
            and not (slot.get("provides") and slot.get("consume"))
            and not (slot.get("provides") and slot.get("kind", "content") != "content")
            for slot in entry.get("slots", {}).values()
        )
    )


def _held_props(entry: dict[str, Any]) -> set[str]:
    """Collect the props a state holder consumes instead of rendering.

    Args:
        entry: The component's schema entry.

    Returns:
        Names the holder fills or observes, so they never reach a native
        parameter and their wire type need not be renderable by an adapter.
    """
    state = entry.get("state")
    if not isinstance(state, dict):
        return set()
    held = {
        name for key in ("value", "report") if isinstance(name := state.get(key), str)
    }
    kind = state.get("kind")
    if isinstance(kind, str):
        held.update(STATE_CONSTRUCTOR_PROPS.get(kind, ()))
        gate = STATE_ATTACH_GATES.get(kind)
        if gate is not None:
            held.add(gate)
    return held


def _mechanical_prop(spec: dict[str, Any]) -> bool:
    """Report whether one prop renders without a human decision.

    Args:
        spec: The prop's schema entry.

    Returns:
        True when the adapter can resolve it from its declared type.
    """
    if "valueType" in spec:
        if spec["type"] == "value" and (
            spec.get("required") or "nativeDefault" in spec
        ):
            return True
        # A colour prop takes a tagged value *or* the legacy string, and the
        # adapter handles both explicitly; no other decoded family does.
        return spec.get("type") == "color" and spec.get("decode") == "color"
    if spec.get("type") in MECHANICAL:
        return True
    # A dp prop carries a plain number and needs no decoder, but only a prop
    # with some default to fall back to can be rendered at all.
    if spec.get("type") == "dp" and _dp_renderable(spec):
        return True
    # Decodable types need a named resolver; without one they cannot be
    # rendered at all rather than rendered wrongly.
    return spec.get("type") in DECODED and bool(spec.get("decode"))


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
    held = _held_props(entry)
    return all(
        prop in held or _mechanical_prop(spec)
        for prop, spec in entry.get("props", {}).items()
    )


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


NUMERIC_KOTLIN = frozenset({"Byte", "Short", "Int", "Long", "Float", "Double"})
"""Kotlin's numeric primitives: the only types a provider coerces between."""

NUMERIC_CONVERSIONS = {
    ("Double", "Float"): "toFloat",
    ("Double", "Int"): "toInt",
    ("Double", "Long"): "toLong",
    ("Float", "Double"): "toDouble",
    ("Int", "Float"): "toFloat",
    ("Int", "Long"): "toLong",
    ("Long", "Double"): "toDouble",
    ("Long", "Float"): "toFloat",
    ("Long", "Int"): "toInt",
}
"""Each entry is Kotlin's own named conversion; an unlisted pair is refused."""


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


def native_name(name: str, entry: dict[str, Any]) -> str:
    """Return the native callable a component schema entry binds.

    A schema entry usually carries its native name. An overload that shares a
    native name with a sibling gets a distinct schema name, and only its
    recorded source says which callable the adapter must invoke.
    """
    source = entry.get("source")
    if isinstance(source, dict):
        native = source.get("name")
        return native if isinstance(native, str) else name
    return name


def composables(name: str, entry: dict[str, Any]) -> set[str]:
    """List the Compose imports one adapter needs beyond the component itself.

    A flattened content slot is its own dependency: ``Button`` compiles without
    ``Text`` in scope until the slot becomes a real ``Text`` call.

    Args:
        name: The native callable the adapter invokes.
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


def _dp_renderable(spec: dict[str, Any]) -> bool:
    """Report whether a dp prop has something to fall back on.

    A dp prop is always passed when it is required or carries a literal model
    default, and an optional one names its pinned default in ``nativeDefault``.
    Without either, a stated value would ride the wire and never reach Compose.

    Args:
        spec: The prop's schema entry.

    Returns:
        True when the adapter can render the prop without a decision.
    """
    return bool(spec.get("required") or "default" in spec or "nativeDefault" in spec)


def scalar_wire(prop_name: str, spec: dict[str, Any]) -> str:
    """Read one scalar from the model, narrowing an Int-native wire value.

    Args:
        prop_name: The camelCase Kotlin property name.
        spec: The prop's schema entry.

    Returns:
        Kotlin source for the value Compose receives.
    """
    wire = f"model.props.{prop_name}"
    if spec.get("nativeType") == "Int":
        wire += "?.toInt()" if spec.get("nullable") else ".toInt()"
    return wire
