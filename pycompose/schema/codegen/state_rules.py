"""Interaction and state rules: the stateful-prop validator family.

Validates interaction sources, reported payloads and state projections;
each claims its native parameters exactly once across the component, so the
wire stays expressible and the host never double-counts.
"""

import re
from typing import Any

from pycompose.core.registry_types import (
    INTERACTION_KINDS,
    STATE_KINDS,
    TRANSIENT_KINDS,
)
from pycompose.schema.codegen.adapter_helpers import (
    STATE_ATTACH_GATES,
    STATE_CONSTRUCTOR_PROPS,
)
from pycompose.schema.codegen.rules import (
    NATIVE_PARAMETER,
    die,
)

INTERACTION_KEYS = frozenset({"native", "observations"})

STATE_KEYS = frozenset({"native", "kind", "value", "report", "dismiss"})

TRANSIENT_KEYS = frozenset({"kind", "native", "serial", "occurrence"})
"""Bounded keys of a transient declaration (ADR-0017 decisions 6-8)."""

STATE_VALUE_TYPES = frozenset({"boolean", "number", "integer"})
"""Scalar prop types a state family can drive; the report answers in one.

A drawer's desired value is a boolean, a scroll offset a number, a list's
first visible index an integer -- whichever it is, the settled report fills
one payload field of the same type, so the host never guesses which scalar
an observation carries.
"""

REPORTED_FIELD = re.compile(r"[a-z][A-Za-z0-9]*")


def _validate_interaction(
    name: str,
    props: dict[str, Any],
    children: dict[str, Any],
    slots: object,
    interaction: object,
) -> None:
    """Check a component's declared interaction source against the vocabulary.

    The interaction source is the host's, not the app's: the schema names the
    native parameter it fills and, per interaction kind, the prop whose action
    observes that kind, and the generator omits those props from the app's
    arguments. Each observed payload is declared once, on its prop, exactly as
    every other host-originated callback declares it.

    Args:
        name: Component name, for error messages.
        props: The component's props; every observed prop must be one of them.
        children: The component's ``children`` object, whose native parameter
            the interaction source must not reuse.
        slots: The component's declared slots, which claim their own natives.
        interaction: The raw ``interaction`` object, or None.
    """
    if interaction is None:
        return
    where = f"component {name!r} interaction"
    if not isinstance(interaction, dict):
        die(f"{where} must be an object")
    unknown = sorted(set(interaction) - INTERACTION_KEYS)
    if unknown:
        die(f"{where} has unknown keys: {', '.join(unknown)}")
    injected = interaction.get("native")
    if not isinstance(injected, str) or not NATIVE_PARAMETER.match(injected):
        die(f"{where}: 'native' must be a parameter name")
    natives = {children.get("native", "content")}
    if isinstance(slots, dict):
        natives.update(
            slot["native"]
            for slot in slots.values()
            if isinstance(slot, dict) and isinstance(slot.get("native"), str)
        )
    if injected in natives or injected in props:
        die(f"{where}: 'native' repeats another parameter")
    observations = interaction.get("observations")
    if not isinstance(observations, dict) or not observations:
        die(f"{where}: 'observations' must be a non-empty object")
    for kind, observed in sorted(observations.items()):
        if kind not in INTERACTION_KINDS:
            die(
                f"{where}: unknown observation {kind!r}; vocabulary: "
                + ", ".join(sorted(INTERACTION_KINDS))
            )
        prop = props.get(observed) if isinstance(observed, str) else None
        if prop is None:
            die(f"{where}: observation {kind!r} must name one of the props")
        if prop.get("type") != "actionId":
            die(f"{where}: prop {observed!r} must be an actionId")
        _validate_reported_payload(where, observed, prop, "boolean")


def _validate_reported_payload(
    where: str, prop_name: object, prop: dict[str, Any], field_type: str
) -> None:
    """Check a host-reported prop carries exactly one payload field of a type.

    The host fills one named field; more fields would mean the host guessed
    which one reports the value, which is what the planner refuses to do
    everywhere else. An interaction observation reports a boolean, and a
    state's report answers in the scalar the family drives.

    Args:
        where: Where the prop was declared, for error messages.
        prop_name: The prop's schema name.
        prop: The prop's schema entry.
        field_type: The single field's required scalar type.
    """
    payload = prop.get("payload")
    field = payload[0] if isinstance(payload, list) and len(payload) == 1 else None
    if (
        not isinstance(field, dict)
        or field.get("type") != field_type
        or not isinstance(field.get("name"), str)
        or REPORTED_FIELD.fullmatch(field["name"]) is None
    ):
        die(f"{where}: prop {prop_name!r} needs one {field_type} payload field")


def _claimed_parameter(where: str, key: str, value: object, claimed: set[str]) -> str:
    """Return one declared native parameter after checking what it claims.

    The state names native parameters the generated call must fill itself, so
    each one has to be a parameter name, and none may be a parameter the
    component's other declarations already name: two arguments for one parameter
    would not compile, and a shadowed prop would never reach the component.

    Args:
        where: Prefix for error messages.
        key: The state key naming the parameter, for the message.
        value: The raw value, which must be a parameter name.
        claimed: Parameters the declaration already names.

    Returns:
        The parameter name.
    """
    if not isinstance(value, str) or NATIVE_PARAMETER.match(value) is None:
        die(f"{where}: {key!r} must be a parameter name")
    if value in claimed:
        die(f"{where}: {key!r} repeats another parameter")
    return value


def _validate_search(where: str, state: dict[str, Any], props: dict[str, Any]) -> None:
    """Check the editing projection a shared search owner exposes.

    Args:
        where: Prefix for validation failures.
        state: The search state declaration.
        props: The component's property contracts.
    """
    _validate_editing_projection(where, props, text="text", report="onEdit")
    if state.get("dismiss") is not None:
        die(f"{where}: search has no dismissal callback")


def _validate_state(
    name: str,
    props: dict[str, Any],
    children: dict[str, Any],
    slots: object,
    state: object,
) -> None:
    """Check a component's declared state holder against the vocabulary.

    The state object is the host's, not the app's: the schema names the native
    parameter it fills, the family whose create/drive/report logic applies, the
    prop carrying Python's desired value, and the prop reporting settled
    changes. The generator omits both props from the app's native arguments,
    exactly as it does for an observed interaction.

    A family may also name a native parameter it *completes* rather than fills
    from a prop: ``dismiss`` is the callback through which the component
    announces a dismissal it has already carried out, which the props above
    already report, so the host answers it with an empty callback.

    Args:
        name: Component name, for error messages.
        props: The component's props; the value and report must be among them.
        children: The component's ``children`` object, whose native parameter
            the state holder must not reuse.
        slots: The component's declared slots, which claim their own natives.
        state: The raw ``state`` object, or None.
    """
    if state is None:
        return
    where = f"component {name!r} state"
    if not isinstance(state, dict):
        die(f"{where} must be an object")
    unknown = sorted(set(state) - STATE_KEYS)
    if unknown:
        die(f"{where} has unknown keys: {', '.join(unknown)}")
    natives = {children.get("native", "content")}
    if isinstance(slots, dict):
        natives.update(
            slot["native"]
            for slot in slots.values()
            if isinstance(slot, dict) and isinstance(slot.get("native"), str)
        )
    claimed = natives | set(props)
    injected = _claimed_parameter(where, "native", state.get("native"), claimed)
    kind = state.get("kind")
    if not isinstance(kind, str) or kind not in STATE_KINDS:
        die(
            f"{where}: unknown state kind {kind!r}; vocabulary: "
            + ", ".join(sorted(STATE_KINDS))
        )
    value = state.get("value")
    prop = props.get(value) if isinstance(value, str) else None
    if prop is None:
        die(f"{where}: 'value' must name one of the props")
    if kind == "textInput":
        _validate_text_input(where, state, props)
        return
    if prop.get("type") not in STATE_VALUE_TYPES:
        # The family drives one scalar -- a drawer is open or it is not, a
        # scroll sits at an offset -- so a prop of any other type cannot carry
        # that family's desired state.
        die(f"{where}: prop {value!r} must be a boolean, number or integer")
    report = state.get("report")
    reported = props.get(report) if isinstance(report, str) else None
    if reported is None:
        die(f"{where}: 'report' must name one of the props")
    if reported.get("type") != "actionId":
        die(f"{where}: prop {report!r} must be an actionId")
    _validate_reported_payload(where, report, reported, prop["type"])
    if kind == "search":
        # A search owner shares one editing projection with every nested
        # surface; the text and its atomic report are fixed names because the
        # holder constructs both states from them.
        _validate_search(where, state, props)
    dismiss = state.get("dismiss")
    if dismiss is not None:
        _claimed_parameter(where, "dismiss", dismiss, claimed | {injected})
    _validate_family_props(where, kind, props)


def _validate_family_props(where: str, kind: str, props: dict[str, Any]) -> None:
    """Check the props a family needs beyond the desired value and its report.

    A family's holder may need more than the two props the block names: a
    ``SliderState`` is constructed from the range and the steps, and a family
    whose holder rides the call's modifier gates the attach with a boolean
    prop. Both are ordinary props the app states, held by the adapter on the
    holder's behalf, so the block's own keys stay bounded.

    Args:
        where: Prefix for error messages.
        kind: The declared state kind.
        props: The component's props.
    """
    missing = [
        extra for extra in STATE_CONSTRUCTOR_PROPS.get(kind, ()) if extra not in props
    ]
    gate = STATE_ATTACH_GATES.get(kind)
    if gate is not None and gate not in props:
        missing.append(gate)
    if missing:
        die(f"{where}: state kind {kind!r} needs the props {', '.join(missing)}")
    if gate is not None and props[gate].get("type") != "boolean":
        die(f"{where}: prop {gate!r} must be a boolean")


def _validate_editing_projection(
    where: str, props: dict[str, Any], *, text: str, report: str | None
) -> None:
    """Text, selection and revision form one required editing projection.

    A component that owns editing names its text prop and its atomic report;
    the bounds are the native UTF-16 selection limits, and the report carries
    all four fields in one payload so a host acknowledgement can never apply a
    text and a selection from different edits.

    Args:
        where: Prefix for validation failures.
        props: The component's property contracts.
        text: Name of the required text prop.
        report: Name of the action reporting the complete editing value, or
            None when the declaration names no report.
    """
    expected = {
        text: "string",
        "selectionStart": "integer",
        "selectionEnd": "integer",
        "revision": "integer",
    }
    for name, kind in expected.items():
        prop = props.get(name, {})
        if prop.get("type") != kind or not prop.get("required"):
            die(f"{where}: prop {name!r} must be a required {kind}")
    for name in ("selectionStart", "selectionEnd", "revision"):
        prop = props[name]
        maximum = 9223372036854775807 if name == "revision" else 2147483647
        if prop.get("minimum") != 0 or prop.get("maximum") != maximum:
            die(f"{where}: prop {name!r} needs native nonnegative bounds")
    report_prop = props.get(report, {}) if report is not None else {}
    payload = report_prop.get("payload", [])
    fields = {field["name"]: field["type"] for field in payload}
    if (
        report_prop.get("type") != "actionId"
        or not report_prop.get("required")
        or len(payload) != 4
        or fields
        != {
            "text": "string",
            "selectionStart": "integer",
            "selectionEnd": "integer",
            "revision": "integer",
        }
    ):
        die(f"{where}: report needs the atomic text/selection/revision payload")


def _validate_text_input(
    where: str, state: dict[str, Any], props: dict[str, Any]
) -> None:
    """Validate a text-input family's editing projection and dismissal rule.

    Args:
        where: Prefix for validation failures.
        state: The text-input state declaration.
        props: The component's property contracts.
    """
    _validate_editing_projection(
        where,
        props,
        text=state["value"],
        report=state.get("report"),
    )
    if state.get("dismiss") is not None:
        die(f"{where}: textInput has no dismissal callback")


def _validate_transient(
    name: str,
    props: dict[str, Any],
    children: dict[str, Any],
    slots: object,
    transient: object,
) -> None:
    """Check a component's declared transient request against the vocabulary.

    The transient is the host's request channel, not the app's: the schema
    names the native parameter the remembered holder fills, the family whose
    remember/fulfil/report logic applies, the prop carrying the serial the
    host compares against the last one it handled, and the occurrence action
    reporting the fulfilled serial back. Both named props are omitted from
    the app's native arguments exactly as a state's are, because the host
    consumes them on the holder's behalf.

    Args:
        name: Component name, for error messages.
        props: The component's props; the serial and occurrence must be them.
        children: The component's ``children`` object, whose native parameter
            the transient holder must not reuse.
        slots: The component's declared slots, which claim their own natives.
        transient: The raw ``transient`` object, or None.
    """
    if transient is None:
        return
    where = f"component {name!r} transient"
    if not isinstance(transient, dict):
        die(f"{where} must be an object")
    unknown = sorted(set(transient) - TRANSIENT_KEYS)
    if unknown:
        die(f"{where} has unknown keys: {', '.join(unknown)}")
    natives = {children.get("native", "content")}
    if isinstance(slots, dict):
        natives.update(
            slot["native"]
            for slot in slots.values()
            if isinstance(slot, dict) and isinstance(slot.get("native"), str)
        )
    claimed = natives | set(props)
    _claimed_parameter(where, "native", transient.get("native"), claimed)
    kind = transient.get("kind")
    if not isinstance(kind, str) or kind not in TRANSIENT_KINDS:
        die(
            f"{where}: unknown transient kind {kind!r}; vocabulary: "
            + ", ".join(sorted(TRANSIENT_KINDS))
        )
    serial = transient.get("serial")
    serial_prop = props.get(serial) if isinstance(serial, str) else None
    if serial_prop is None:
        die(f"{where}: 'serial' must name one of the props")
    if serial_prop.get("type") != "integer":
        # The host compares serials numerically, one request after another;
        # anything else would make "bumped" a string-editing question.
        die(f"{where}: prop {serial!r} must be an integer")
    occurrence = transient.get("occurrence")
    reported = props.get(occurrence) if isinstance(occurrence, str) else None
    if reported is None:
        die(f"{where}: 'occurrence' must name one of the props")
    if reported.get("type") != "actionId":
        die(f"{where}: prop {occurrence!r} must be an actionId")
    _validate_reported_payload(where, occurrence, reported, serial_prop["type"])
