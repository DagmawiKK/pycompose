"""The classified lock diff: what a regenerated lock means for an app."""

from __future__ import annotations

import copy
from typing import Any

from pycompose.compiler.diff import Change, classify, unapproved

BASE: dict[str, Any] = {
    "schemaVersion": "1.23.0",
    "components": {
        "Chip": {
            "category": "input",
            "source": {"artifact": "m3:1.4.0", "owner": "o", "jvmName": "Chip"},
            "props": {
                "label": {"type": "string", "required": True},
                "style": {"type": "enum", "values": ["a", "b"], "default": "a"},
                "count": {"type": "integer", "minimum": 0, "maximum": 9},
            },
            "children": {"allowed": True},
            "state": {"native": "state", "kind": "drawer"},
        }
    },
    "valueTypes": {"Shape": {"family": "Shape"}},
}


def _after(edit) -> list[Change]:
    new = copy.deepcopy(BASE)
    edit(new["components"]["Chip"])
    return classify(BASE, new)


def _kinds(changes: list[Change]) -> dict[str, str]:
    return {change.id: change.kind for change in changes}


def test_new_api_is_additive_and_removed_api_breaks() -> None:
    new = copy.deepcopy(BASE)
    new["components"]["Badge"] = {"props": {}}
    del new["valueTypes"]["Shape"]
    assert _kinds(classify(BASE, new)) == {
        "components.Badge:added": "additive",
        "valueTypes.Shape:removed": "breaking",
    }


def test_a_prop_an_app_must_now_pass_breaks_it() -> None:
    def edit(chip: dict[str, Any]) -> None:
        chip["props"]["icon"] = {"type": "string", "required": True}
        chip["props"]["tint"] = {"type": "color"}
        chip["props"]["label"]["required"] = False

    assert _kinds(_after(edit)) == {
        "components.Chip.props.icon:added": "breaking",
        "components.Chip.props.label.required:changed": "additive",
        "components.Chip.props.tint:added": "additive",
    }


def test_narrowed_vocabularies_break_and_widened_ones_add() -> None:
    def edit(chip: dict[str, Any]) -> None:
        chip["props"]["style"]["values"] = ["a"]
        chip["props"]["count"]["maximum"] = 99
        chip["props"]["count"]["minimum"] = 1

    assert _kinds(_after(edit)) == {
        "components.Chip.props.count.maximum:changed": "additive",
        "components.Chip.props.count.minimum:changed": "breaking",
        "components.Chip.props.style.values:changed": "breaking",
    }


def test_defaults_and_pin_bumps_are_fidelity() -> None:
    def edit(chip: dict[str, Any]) -> None:
        chip["props"]["style"]["default"] = "b"
        chip["source"]["artifact"] = "m3:1.5.0"
        chip["category"] = "buttons"

    assert _kinds(_after(edit)) == {
        "components.Chip.category:changed": "metadata",
        "components.Chip.props.style.default:changed": "fidelity",
        "components.Chip.source:changed": "fidelity",
    }


def test_state_and_overload_changes_are_behaviour() -> None:
    def edit(chip: dict[str, Any]) -> None:
        chip["state"]["kind"] = "sheet"
        chip["source"]["jvmName"] = "Chip-x"
        chip["children"]["allowed"] = False

    assert _kinds(_after(edit)) == {
        "components.Chip.children:changed": "breaking",
        "components.Chip.source:changed": "behaviour",
        "components.Chip.state:changed": "behaviour",
    }


def test_behaviour_needs_an_approval_and_approvals_must_be_current() -> None:
    changes = [
        Change("components.Chip.state:changed", "behaviour"),
        Change("components.Chip.since:changed", "metadata"),
    ]
    missing, stale = unapproved(changes, {"components.Gone:removed": "old"})
    assert missing == [changes[0]]
    assert stale == ["components.Gone:removed"]
    assert unapproved(changes, {changes[0].id: "drawer became a sheet"}) == ([], [])


def test_observation_added_to_a_component_is_additive() -> None:
    def edit(chip: dict[str, Any]) -> None:
        chip["interaction"] = {"native": "source", "observations": {"press": "onPress"}}
        chip["props"]["onPress"] = {"type": "actionId", "payload": []}

    assert _kinds(_after(edit)) == {
        "components.Chip.interaction:added": "additive",
        "components.Chip.props.onPress:added": "additive",
    }


def test_a_value_binding_repinned_to_a_newer_artifact_is_fidelity() -> None:
    def value(version: str, default: int = 0) -> dict[str, Any]:
        source = {"artifact": f"g:a:{version}", "owner": "O", "jvmName": "c"}
        return {"valueTypes": {"Dp": {"source": source, "default": default}}}

    assert classify(value("1"), value("2")) == [
        Change("valueTypes.Dp.source:changed", "fidelity")
    ]
    # Anything else that changed is still a behaviour change.
    assert classify(value("1"), value("2", default=1)) == [
        Change("valueTypes.Dp:changed", "behaviour")
    ]
