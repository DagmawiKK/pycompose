"""What the host owns for a node: interaction sources, state holders, transients.

The renderer remembers each per node id; the adapter fetches it into a local and
hands it to the native parameter, while the props carrying the app's desired
state and its reports never reach the component.
"""

from __future__ import annotations

from typing import Any

from pycompose.contract.registry_vocabulary import STATE_STREAMS
from pycompose_codegen.emit.adapters.fragments import Fragments
from pycompose_codegen.emit.adapters.policy import camel
from pycompose_codegen.emit.adapters.props import render_value
from pycompose_codegen.emit.derived_families import properties_locals
from pycompose_codegen.emit.state_families import (
    STATE_CONSTRUCTOR_PROPS,
    attach_gate,
)


def state_call(kind: str) -> str:
    """Name the renderer method a state family's host holder comes from.

    The family decides the create/drive/report logic; the schema decides which
    component has one. A family the renderer does not implement fails the
    generated adapters' compile proof.

    Args:
        kind: A ``STATE_KINDS`` member.

    Returns:
        ``<kind>State``, e.g. ``drawerState``.
    """
    return f"{kind}State"


GATED_STATES = frozenset({"sheet"})
"""State families whose native component must be composed conditionally.

``ModalBottomSheet`` shows itself as soon as it is composed and measured, and a
composed sheet keeps its own window in front of the app even while hidden, so
presence is the only way to show one and absence the only way to let the app
through. A gated family's holder carries the native state in ``state`` and the
composition gate in ``visible``; any other family's holder is the native state
itself.
"""


def host_locals(entry: dict[str, Any], out: Fragments) -> str | None:
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
        locals_, arguments, gate = _state(state, entry.get("props", {}))
        out.locals.extend(locals_)
        out.arguments.extend(arguments)
        if state["kind"] in STATE_STREAMS:
            # Expressions anywhere in the snapshot may read this holder's streams.
            out.locals.append(f"context.publish(model.id, {state['native']}Value)")
        if (
            state["kind"] == "lazyList"
            and entry.get("children", {}).get("kind") == "items"
        ):
            # The list asks for the window it shows as the user scrolls.
            out.locals.append(
                f"context.RequestWindows({state['native']}Value, model.props.window, "
                "model.props.itemOffset, model.children.unslotted().size)"
            )
        attach = attach_gate(state, entry.get("props", {}))
        if attach is not None:
            # The holder rides the modifier: the component's first argument is
            # the attach itself, gated by the prop the app states.
            out.arguments[0] = (
                f"modifier = {state['native']}Value.attachTo("
                f"modifier, model.props.{camel(attach)})"
            )
    if transient is not None:
        out.locals.append(_transient(transient, entry.get("props", {})))
        out.arguments.append(f"{transient['native']} = {transient['native']}Value")
    return gate


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
        f'"{kind}" to model.props.{camel(observations[kind])}'
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
) -> tuple[list[str], list[str], str | None]:
    """Render the locals that fetch one component's host-owned state holder.

    The holder is the renderer's, remembered per node id; the desired value and
    the report channel are ordinary props, so the app keeps naming its own
    fields and the host never holds a Python object. Props the holder is
    constructed from reach the renderer's call too, resolved where the ordinary
    value props are resolved.

    Args:
        state: The component's raw ``state`` entry.
        props: The component's declared props, by wire name.

    Returns:
        The Kotlin locals, the native arguments consuming the holder, and the
        expression gating the call for a family that must be composed
        conditionally, or None when the component is always composed.
    """
    native = state["native"]
    if state["kind"] == "properties":
        return properties_locals(state), [f"{native} = {native}Value"], None
    held = f"{native}Value"
    value = camel(state["value"])
    report = camel(state["report"])
    gated = state["kind"] in GATED_STATES
    # An attach family fills no parameter: its holder rides the modifier the
    # composer rewrites, and the component is composed unconditionally.
    attached = attach_gate(state, props) is not None
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
        [
            f"val {held} = context.{state_call(state['kind'])}("
            f"model.props.{value}, model.props.{report}{extras})"
        ],
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
    prop = camel(name)
    if spec.get("type") == "value" and "valueType" in spec:
        return f"{prop}Value"
    return f"model.props.{prop}"


def resolve_constructor(
    state: dict[str, Any] | None,
    props: dict[str, Any],
    out: Fragments,
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
        resolved = Fragments()
        if not render_value(camel(name), spec, resolved):
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
        f"{name} = model.props.{camel(name)}"
        for name in sorted(props)
        if name != "modifier"
    )
    call = transient["kind"]
    return f"val {transient['native']}Value = context.{call}(model.id, {entries})"
