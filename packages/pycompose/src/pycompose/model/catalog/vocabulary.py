"""The closed vocabularies of the component registry.

One module owns every closed set the registry, the codegen and the pin
audit speak: slot kinds, interaction and state families, prop owners,
adapter modes and decoders. A closed set that two layers must agree on is safest
when the second definition cannot exist: these tuples are the only
copies, and every other file imports its names from here --
``registry`` re-exports them on its established import surface.
Tests assert the agreements (for example, scope paths pairing with scope
names); they never copy the values.
"""

from __future__ import annotations

OWNERS = ("python", "host")
"""Who may set a prop. Anything else is refused rather than ignored."""

SLOT_KINDS = ("content", "items", "keyed", "indexed")
"""How a subtree is composed: nodes in order, lazy list items, one per key, or one
per index.

``keyed`` is the primary children's alone: keyed content draws the subtree Python
sent for the current key, and keeps an outgoing key's while it animates out.
``indexed`` is a template over an index (a pager's ``page``): the i-th child is
what the lambda draws for index i.
"""

CONSUMERS = ("paddingValues",)
"""Slot scopes the adapter consumes on the subtree's behalf.

A consumed scope is never lost: the adapter applies it in the one place Compose
idiomatically applies it, and the app cannot apply it twice.
"""

INTERACTION_KINDS = ("press", "focus", "hover")
"""Interaction kinds the host can observe and report as actions."""

INTERACTION_REPORTS = {"press": "pressed", "focus": "focused", "hover": "hovered"}
"""The boolean payload field each observed interaction reports."""

STATE_KINDS = (
    "sheet",
    "tooltip",
    "textInput",
)
"""State families the host creates, drives and reports for a component.

A family is one host-side implementation, kept by hand only where the pin lacks
what a derived family needs; each names that member or protocol:

* ``sheet`` -- ``ModalBottomSheet`` shows its own window as soon as it is
  composed and keeps it while hidden, so presence is composition: the host
  composes it to show it and removes it once hidden, which no holder member
  states.
* ``tooltip`` -- ``TooltipState.isVisible`` is read-only and moves through
  ``show()``, which also starts a non-persistent tooltip's timeout and must
  wait out its anchor's focus initialization; re-creating the holder would skip
  both, and the pin gives no evidence of which value ``show()`` and
  ``dismiss()`` set.
* ``textInput`` -- ``TextFieldState.text`` and ``selection`` are read-only and
  change only inside ``edit { }``, a ``TextFieldBuffer`` block no type rule
  drives; its reports are numbered, atomic text-and-selection edits, so an
  input method's composition survives the app's answers (ADR-0023).

A holder with one scrollable position (a pager's page, a list's first visible
item, a scroll's offset), one anchor of an enum (a drawer open or closed, a
swipe settled or dismissed) or properties (a slider's value, a time picker's
hour, a date range picker's selection, re-created to change) is derived, and
one node may use a holder another owns by naming it (a search bar's state,
shared with its input field and its expanded surface) from the pin
instead (``positional``, ``anchored``,
``properties``). The vocabulary is closed for the same reason the interaction
kinds are: the host must not be asked to drive a state object whose
transitions it does not understand.
"""

STATE_HOLDERS = {
    "sheet": "androidx.compose.material3.SheetState",
    "tooltip": "androidx.compose.material3.TooltipState",
    "textInput": "androidx.compose.foundation.text.input.TextFieldState",
}
"""The native holder each state family creates and drives.

A component parameter of one of these types is filled by the host's family
implementation, never by the wire, so the pin alone says which family a
component binds.
"""

ADAPTERS = ("generated", "manual")
"""Whether the Kotlin adapter is derived from the schema or written by hand."""

TRANSIENT_KINDS = ("snackbar",)
"""Transient families the host requests, fulfils and reports for a component.

A transient is a serial-numbered fire-and-forget occurrence, not a continuous
value: naming a snackbar's "current value" would be a lie (ADR-0017 decisions
6-8). The host remembers the last serial it handled under the node's identity,
shows a request whose serial it has not seen, and reports the fulfilled serial
back as an action, so an identical re-rendered snapshot is a no-op while a
deliberate repeat of identical content is a new serial. The vocabulary is
closed for the same reason the state kinds are: the host must not be asked to
fulfil a request whose semantics it does not understand.
"""

DECODED_TYPES = ("resource",)
"""Prop types whose Kotlin type is not the wire type, and so need a decoder."""

DECODERS = ("resourceFont", "resourceImage", "resourceText")
"""The host resolvers a prop may name: resources, which load off the main thread.

Every other family a prop names crosses the wire as its tagged value."""

STATE_STREAMS = {
    "androidx.compose.material3.DrawerState": ("progress",),
    "androidx.compose.foundation.ScrollState": ("offset", "progress"),
}
"""Streams each holder class exposes to expressions, whichever family drives it.

A stream is a number the host reads from the holder every frame -- a drawer's
open fraction, a scroll's offset and fraction -- so a prop bound to an
expression over it follows a gesture without Python running per frame.
"""


def holder_streams(kind: str, holder: object = None) -> tuple[str, ...]:
    """The streams a state's holder exposes: a derived family names its holder,
    a hand-written one is its kind's.

    Args:
        kind: The state's family.
        holder: The holder class a derived family names, if any.

    Returns:
        The stream names, none for a holder that exposes none.
    """
    named = holder if isinstance(holder, str) else STATE_HOLDERS.get(kind, "")
    return STATE_STREAMS.get(named, ())


EXPRESSION_OPS = ("times", "plus", "minus", "clamp", "alpha", "mix")
"""The closed expression vocabulary: arithmetic and clamp over numbers, and the
two ways a number becomes a colour (a colour's alpha, a mix of two colours).
No loops, recursion or user functions: evaluation is linear in the size."""

EXPRESSION_LIMITS = {"depth": 8, "nodes": 32}
"""The largest expression a snapshot may carry, checked by both validators."""

_NUMERIC = ("integer", "number")
_TYPES = ("integer", "number", "boolean", "string")

FUNCTION_TYPES = _TYPES
"""The types a value function takes and answers: an enum argument is a string."""

FUNCTION_SIGNATURES: dict[str, dict[tuple[str, ...], str]] = {
    **{op: {(t, t): t for t in _NUMERIC} for op in ("plus", "minus", "times")},
    "neg": {(t,): t for t in _NUMERIC},
    "div": {("number", "number"): "number"},
    **{op: {("integer", "integer"): "integer"} for op in ("floorDiv", "mod")},
    "toNumber": {("integer",): "number"},
    **{op: {(t, t): "boolean" for t in _NUMERIC} for op in ("lt", "le", "gt", "ge")},
    **{op: {(t, t): "boolean" for t in _TYPES} for op in ("eq", "ne")},
    **{op: {("boolean", "boolean"): "boolean"} for op in ("and", "or")},
    "not": {("boolean",): "boolean"},
    "if": {("boolean", t, t): t for t in _TYPES},
    **{op: {("number",): "number"} for op in ("sin", "cos")},
}
"""The closed vocabulary of a value function the host calls: each operation's
argument types and the type it gives. Arithmetic, comparison, logic and a
conditional over integers, numbers and booleans, and equality and the
conditional over strings (an enum argument is its wire spelling); every
operation is total and
there are no loops or calls, so a call costs at most its size. Both checkers
type a program from this one table."""

FUNCTION_LIMITS = {"depth": 32, "nodes": 256, "arguments": 8}
"""The largest value function a snapshot may carry, checked by both validators."""

DRAW_LIMITS = {"nodes": 4096, "draws": 4096, "repeat": 1024, "loops": 3}
"""The largest draw program a snapshot may carry: its nodes in all, the draw
calls it can make in one frame (counted through its loops), the count one loop
may run, and how deeply loops nest. Checked by both validators, so a frame's
work is bounded before the program first runs."""

TRANSIENT_HOLDERS = {"snackbar": "androidx.compose.material3.SnackbarHostState"}
"""The native holder each transient family remembers and fulfils requests on."""

RESOURCE_TYPES = {
    "androidx.compose.ui.graphics.painter.Painter": (
        "resourceImage",
        ("drawable", "asset", "file"),
    ),
}
"""Native types the wire fills with a resource reference: decoder and kinds.

The host loads the referenced resource and hands the native call the result,
so a parameter of such a type is a ``resource`` prop, not a value family.
"""

LAYOUT_LIMITS = {"nodes": 4096, "repeat": 1024, "loops": 3}
"""The largest layout program a snapshot may carry: its nodes in all, the count
one literal loop may run, and how deeply loops nest. A loop over the children
runs once per child, which the host has measured, so it needs no count."""

LAYOUT_CALLS: dict[str, tuple[str, ...]] = {
    "place": ("integer", "number", "number"),
    "size": ("number", "number"),
}
"""What a layout program's statements do: place a child (its index, x and y in
px), and state the layout's own size; the last size stated stands."""

LAYOUT_SIGNATURES: dict[str, dict[tuple[str, ...], str]] = {
    "childWidth": {("integer",): "number"},
    "childHeight": {("integer",): "number"},
}
"""What a layout program's expressions add: a child's measured width and
height, by index; one out of range measures 0."""
