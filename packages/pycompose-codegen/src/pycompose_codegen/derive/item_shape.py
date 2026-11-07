"""The wire shape of builder members and of holders handed to slots.

``wire_shape`` places every lambda as children or a named slot. Two plans need
more: a builder whose scope's members are items takes item components (kind
``members``), and a slot handed a holder projects the holder's property onto
the component (``members.handed_holders``).
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.candidate_props import CandidateError


def place_members(
    name: str,
    plan: dict[str, Any],
    props: dict[str, Any],
    children: dict[str, Any],
    slots: dict[str, Any],
) -> list[str]:
    """Mark builder-member channels and project handed holders, in place.

    Args:
        name: The component's schema name, for refusals.
        plan: Its call plan.
        props: The props ``wire_shape`` derived.
        children: The children block it derived.
        slots: The named slots it derived.

    Returns:
        Review notes for what changed.

    Raises:
        CandidateError: Two handed holders project the same property, or one
            collides with a prop.
    """
    review: list[str] = []
    for parameter, spec in plan["parameters"].items():
        if spec["policy"] != "slot":
            continue
        channel = slots.get(parameter, children if parameter == "content" else None)
        if channel is None:
            continue
        if spec.get("kind") == "members":
            # Item components, each applied to the scope as the builder runs.
            channel["kind"] = "members"
            channel["applies"] = list(spec["applies"])
            review.append(f"{parameter}: builder members, one item component each")
        handed = spec.get("handed")
        if handed is not None:
            channel["handed"] = dict(handed)
            value = handed["value"]
            report = f"on{value[:1].upper()}{value[1:]}Change"
            if value in props or report in props:
                raise CandidateError(
                    f"{name}: {parameter} hands {value}, already a prop"
                )
            props[value] = {"type": "boolean"}
            props[report] = {
                "type": "actionId",
                "payload": [{"name": value, "type": "boolean"}],
            }
            review.append(
                f"{parameter}: handed {handed['holder'].rsplit('.', 1)[-1]}; "
                f"{value} projected"
            )
    return review
