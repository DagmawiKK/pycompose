"""The closed vocabularies of the component registry.

One module owns every closed set the registry, the codegen and the pin
audit speak: slot kinds, scope names and their compiler paths,
interaction and state families, prop owners, adapter modes, decoders and
delegating wrappers. A closed set that two layers must agree on is safest
when the second definition cannot exist: these tuples are the only
copies, and every other file imports its names from here --
``registry_types`` re-exports them on its established import surface.
Tests assert the agreements (for example, scope paths pairing with scope
names); they never copy the values.
"""

from __future__ import annotations

OWNERS = ("python", "host")
"""Who may set a prop. Anything else is refused rather than ignored."""

SLOT_KINDS = ("content", "items")
"""How a slot's subtree is composed: nodes in order, or lazy list items."""

CONSUMERS = ("paddingValues",)
"""Slot scopes the adapter consumes on the subtree's behalf.

A consumed scope is never lost: the adapter applies it in the one place Compose
idiomatically applies it, and the app cannot apply it twice.
"""

SCOPES = (
    "RowScope",
    "ColumnScope",
    "BoxScope",
    "SingleChoiceSegmentedButtonRowScope",
    "MultiChoiceSegmentedButtonRowScope",
    "TooltipScope",
)
"""Composition scopes a component can require or hand to its children.

Closed like :data:`CONSUMERS`: the renderer owns one registration path per scope,
so a name outside this tuple has no path to land in. The first three are layout
scopes; the segmented-button rows and the tooltip add receivers whose members
exist only inside their own content lambdas.
"""

SCOPE_PATHS = {
    "RowScope": "androidx.compose.foundation.layout.RowScope",
    "ColumnScope": "androidx.compose.foundation.layout.ColumnScope",
    "BoxScope": "androidx.compose.foundation.layout.BoxScope",
    "SingleChoiceSegmentedButtonRowScope": (
        "androidx.compose.material3.SingleChoiceSegmentedButtonRowScope"
    ),
    "MultiChoiceSegmentedButtonRowScope": (
        "androidx.compose.material3.MultiChoiceSegmentedButtonRowScope"
    ),
    "TooltipScope": "androidx.compose.material3.TooltipScope",
}
"""Name -> fully-qualified receiver path for every member of :data:`SCOPES`.

Paired with the closed tuple and verified against it by the vocabulary tests;
codegen and the pin audit derive the compiler's slash form from these paths, so
no second path table exists anywhere.
"""

INTERACTION_KINDS = ("press", "focus", "hover")
"""Interaction kinds the host can observe and report as actions."""

INTERACTION_REPORTS = {"press": "pressed", "focus": "focused", "hover": "hovered"}
"""The boolean payload field each observed interaction reports."""

STATE_KINDS = (
    "drawer",
    "sheet",
    "slider",
    "scroll",
    "lazyList",
    "tooltip",
    "textInput",
    "search",
    "swipe",
)
"""State families the host creates, drives and reports for a component.

A family is one host-side implementation: a drawer reconciles a desired
open/closed value through gestures and animation; a sheet does the same for a
modal surface that has to be composed to be shown at all; a slider drives the
thumb to a desired number and reports the settled one; scroll and lazyList
report a resting position once scrolling comes to rest; a tooltip reconciles a
desired visible value through hover, focus and long-press gestures; textInput
reconciles text and selection with a revisioned atomic edit report; search
shares one editing projection and one expansion state across a collapsed bar
and every expanded surface; a swipe reconciles a desired settled/dismissed
anchor through horizontal gestures and reports the anchor it settled on. The
vocabulary is closed for the same reason the interaction kinds are: the host
must not be asked to drive a state object whose transitions it does not
understand.
"""

STATE_HOLDERS = {
    "drawer": "androidx.compose.material3.DrawerState",
    "sheet": "androidx.compose.material3.SheetState",
    "slider": "androidx.compose.material3.SliderState",
    "scroll": "androidx.compose.foundation.ScrollState",
    "lazyList": "androidx.compose.foundation.lazy.LazyListState",
    "tooltip": "androidx.compose.material3.TooltipState",
    "textInput": "androidx.compose.foundation.text.input.TextFieldState",
    "search": "androidx.compose.material3.SearchBarState",
    "swipe": "androidx.compose.material3.SwipeToDismissBoxState",
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

DECODED_TYPES = ("enum", "color", "resource")
"""Prop types whose Kotlin type is not the wire type, and so need a decoder."""

DECODERS = (
    "alignment",
    "arrangement",
    "color",
    "horizontal",
    "resourceFont",
    "resourceImage",
    "resourceText",
    "textStyle",
    "tooltipPosition",
    "vertical",
)
"""The host resolvers a prop may name."""

STATE_STREAMS = {"drawer": ("progress",), "scroll": ("offset", "progress")}
"""Streams each state family's holder exposes to expressions (plan 31 §6).

A stream is a number the host reads from the holder every frame -- a drawer's
open fraction, a scroll's offset and fraction -- so a prop bound to an
expression over it follows a gesture without Python running per frame.
"""

EXPRESSION_OPS = ("times", "plus", "minus", "clamp", "alpha", "mix")
"""The closed expression vocabulary: arithmetic and clamp over numbers, and the
two ways a number becomes a colour (a colour's alpha, a mix of two colours).
No loops, recursion or user functions: evaluation is linear in the size."""

EXPRESSION_LIMITS = {"depth": 8, "nodes": 32}
"""The largest expression a snapshot may carry, checked by both validators."""

TRANSIENT_HOLDERS = {"snackbar": "androidx.compose.material3.SnackbarHostState"}
"""The native holder each transient family remembers and fulfils requests on."""

HOST_VALUES = {
    "androidx.compose.ui.window.PopupPositionProvider": (
        "position",
        {
            "type": "enum",
            "decode": "tooltipPosition",
            "values": ["above", "below", "left", "right", "start", "end"],
            "default": "above",
        },
    ),
}
"""Native types the host builds from a wire prop it names: the prop and its spec.

A popup position provider measures the anchor and the screen, which the app
cannot; the app states where the popup goes and the host builds the provider.
"""

RESOURCE_TYPES = {
    "androidx.compose.ui.graphics.painter.Painter": (
        "resourceImage",
        ("drawable", "asset"),
    ),
}
"""Native types the wire fills with a resource reference: decoder and kinds.

The host loads the referenced resource and hands the native call the result,
so a parameter of such a type is a ``resource`` prop, not a value family.
"""

WRAPPERS = ("ResourceText", "ResourceImage")
"""Composables an adapter may delegate to whole.

A wrapper resolves its content asynchronously -- off the Compose thread, with
its own diagnostics -- so it cannot be expressed as a resolved prop value. The
call site is mechanical; what it delegates to is not.
"""
