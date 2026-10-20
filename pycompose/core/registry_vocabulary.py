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
)
"""Composition scopes a component can require or hand to its children.

Closed like :data:`CONSUMERS`: the renderer owns one registration path per scope,
so a name outside this tuple has no path to land in. The first three are layout
scopes; the segmented-button rows add receivers whose members exist only inside
their own content lambdas.
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
}
"""Name -> fully-qualified receiver path for every member of :data:`SCOPES`.

Paired with the closed tuple and verified against it by the vocabulary tests;
codegen and the pin audit derive the compiler's slash form from these paths, so
no second path table exists anywhere.
"""

INTERACTION_KINDS = ("press", "focus", "hover")
"""Interaction kinds the host can observe and report as actions."""

STATE_KINDS = ("drawer", "sheet", "slider", "scroll", "lazyList")
"""State families the host creates, drives and reports for a component.

A family is one host-side implementation: a drawer reconciles a desired
open/closed value through gestures and animation; a sheet does the same for a
modal surface that has to be composed to be shown at all; a slider drives the
thumb to a desired number and reports the settled one; scroll and lazyList
report a resting position once scrolling comes to rest. The vocabulary is
closed for the same reason the interaction kinds are: the host must not be
asked to drive a state object whose transitions it does not understand.
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
    "vertical",
)
"""The host resolvers a prop may name."""

WRAPPERS = ("ResourceText", "ResourceImage")
"""Composables an adapter may delegate to whole.

A wrapper resolves its content asynchronously -- off the Compose thread, with
its own diagnostics -- so it cannot be expressed as a resolved prop value. The
call site is mechanical; what it delegates to is not.
"""
