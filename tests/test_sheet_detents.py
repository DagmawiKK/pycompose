"""Sheet detents extend, rather than replace, the boolean authoring surface."""

import json
from pathlib import Path
from typing import Any

import pytest
from test_state_projection import load_with, snapshot

from pycompose.contract.catalog import REGISTRY
from pycompose.material3 import ModalBottomSheet, Text
from pycompose.wire.validator import validate_prop


def test_a_sheet_can_state_an_expanded_anchor_and_observe_it() -> None:
    """The generated API carries detent control without exposing a native holder."""
    wire = snapshot(
        ModalBottomSheet(
            id="sheet",
            value="expanded",
            on_value_change="submit",
            children=[Text(id="body", text="Body")],
        )
    )["root"]
    assert wire["props"] == {"value": "expanded", "onValueChange": "submit"}


@pytest.mark.parametrize("anchor", ["hidden", "partiallyExpanded", "expanded"])
def test_each_native_sheet_anchor_is_accepted(anchor: str) -> None:
    """All three anchors cross the data-only boundary."""
    wire = snapshot(ModalBottomSheet(id="sheet", value=anchor))["root"]
    assert wire["props"] == {"value": anchor}


def test_a_sheet_still_accepts_the_legacy_boolean_contract() -> None:
    """Existing app source needs no migration and no new prop is inserted."""
    wire = snapshot(ModalBottomSheet(id="sheet", open=True, on_open_change="submit"))[
        "root"
    ]
    assert wire["props"] == {"open": True, "onOpenChange": "submit"}


def test_a_sheet_can_observe_both_presence_and_detents() -> None:
    """The additive observers coexist on one data-only contract."""
    wire = snapshot(
        ModalBottomSheet(
            id="sheet",
            open=True,
            on_open_change="submit",
            value="expanded",
            on_value_change="increment",
        )
    )["root"]
    assert wire["props"] == {
        "open": True,
        "onOpenChange": "submit",
        "value": "expanded",
        "onValueChange": "increment",
    }


def test_the_sheet_anchor_is_a_closed_enum() -> None:
    """Invalid anchors fail validation rather than falling through to a guess."""
    spec = REGISTRY.components["ModalBottomSheet"].props["value"]
    assert spec.values == ("hidden", "partiallyExpanded", "expanded")
    assert not validate_prop("half", spec)
    assert not validate_prop(True, spec)


def test_the_sheet_family_declares_both_optional_projections() -> None:
    """Presence and detents share one holder, each with its own typed report."""
    spec = REGISTRY.components["ModalBottomSheet"]
    assert spec.state is not None
    assert spec.state.kind == "sheet"
    assert (spec.state.value, spec.state.report) == ("open", "onOpenChange")
    assert spec.state.dismiss == "onDismissRequest"
    assert not spec.props["value"].required
    assert not spec.props["skipPartiallyExpanded"].required
    assert spec.props["skipPartiallyExpanded"].default is False
    assert spec.props["onValueChange"].payload == (("value", "string"),)
    assert spec.props["onOpenChange"].payload == (("open", "boolean"),)


def test_the_app_can_disable_the_partial_anchor() -> None:
    """The holder policy is a boolean, not a native object or pixel offset."""
    wire = snapshot(
        ModalBottomSheet(id="sheet", value="expanded", skip_partially_expanded=True)
    )["root"]
    assert wire["props"] == {"value": "expanded", "skipPartiallyExpanded": True}


def test_codegen_refuses_a_sheet_report_with_the_wrong_payload_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A holder report cannot be declared as a boolean while dispatching strings."""
    with pytest.raises(SystemExit, match="needs one string payload field"):
        load_with(
            tmp_path,
            monkeypatch,
            lambda registry: registry["components"]["ModalBottomSheet"]["props"][
                "onValueChange"
            ]["payload"][0].update(type="boolean"),
        )


@pytest.mark.parametrize(
    ("prop", "replacement", "message"),
    [
        ("value", {"type": "string"}, "must be an enum with the values"),
        (
            "value",
            {"type": "enum", "values": ["hidden", "expanded"]},
            "must be an enum with the values",
        ),
        (
            "value",
            {
                "type": "enum",
                "values": ["hidden", "partiallyExpanded", "expanded"],
                "required": True,
            },
            "must be optional",
        ),
        (
            "value",
            {
                "type": "enum",
                "values": ["hidden", "partiallyExpanded", "expanded"],
                "default": "expanded",
            },
            "must not declare a default",
        ),
    ],
)
def test_codegen_refuses_a_holder_contract_it_cannot_drive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prop: str,
    replacement: dict[str, Any],
    message: str,
) -> None:
    """Anchor and constructor-policy types cannot drift from the native holder."""
    with pytest.raises(SystemExit, match=message):
        load_with(
            tmp_path,
            monkeypatch,
            lambda registry: registry["components"]["ModalBottomSheet"]["props"].update(
                {prop: replacement}
            ),
        )


@pytest.mark.parametrize(
    ("report", "field"),
    [("onValueChange", "value"), ("onOpenChange", "open")],
)
def test_codegen_refuses_a_report_with_the_wrong_field_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report: str,
    field: str,
) -> None:
    """A report the host cannot fill would be a silently unobservable action."""
    with pytest.raises(SystemExit, match=f"must optionally report '{field}'"):
        load_with(
            tmp_path,
            monkeypatch,
            lambda registry: registry["components"]["ModalBottomSheet"]["props"][
                report
            ]["payload"][0].update(name="other"),
        )


@pytest.mark.parametrize(
    ("report", "field"),
    [("onValueChange", "value"), ("onOpenChange", "open")],
)
def test_codegen_refuses_a_required_sheet_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report: str,
    field: str,
) -> None:
    """Neither observer is required; an app may drive the sheet silently."""
    with pytest.raises(SystemExit, match=f"must optionally report '{field}'"):
        load_with(
            tmp_path,
            monkeypatch,
            lambda registry: registry["components"]["ModalBottomSheet"]["props"][
                report
            ].update(required=True),
        )


def test_codegen_refuses_a_multi_field_sheet_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A generated event carries exactly the one field the contract names."""
    with pytest.raises(SystemExit, match="needs one string payload field"):
        load_with(
            tmp_path,
            monkeypatch,
            lambda registry: registry["components"]["ModalBottomSheet"]["props"][
                "onValueChange"
            ]["payload"].append({"name": "extra", "type": "string"}),
        )


def test_codegen_refuses_a_missing_anchor_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The family's extra projection is declared, not assumed by the renderer."""
    with pytest.raises(SystemExit, match="needs the props onValueChange"):
        load_with(
            tmp_path,
            monkeypatch,
            lambda registry: registry["components"]["ModalBottomSheet"]["props"].pop(
                "onValueChange"
            ),
        )


@pytest.mark.parametrize(
    "replacement",
    [
        {"type": "number", "default": False},
        {"type": "boolean", "default": True},
        {"type": "boolean"},
        {"type": "boolean", "default": False, "required": True},
    ],
)
def test_codegen_refuses_an_invalid_partial_anchor_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: dict[str, Any],
) -> None:
    """The holder policy is exactly one optional boolean whose default is false."""
    with pytest.raises(SystemExit, match="optional boolean defaulting to false"):
        load_with(
            tmp_path,
            monkeypatch,
            lambda registry: registry["components"]["ModalBottomSheet"]["props"].update(
                {"skipPartiallyExpanded": replacement}
            ),
        )


def test_sheet_detents_are_gated_to_the_current_envelope() -> None:
    """Released envelopes must reject props they never declared."""
    schema = json.loads(
        (
            Path(__file__).resolve().parent.parent / "schema" / "ir.schema.json"
        ).read_text()
    )
    for version in ("1.19.0", "1.20.0", "1.21.0", "1.22.0"):
        name = f"V_{version.replace('.', '_')}_ModalBottomSheet"
        props = schema["definitions"][name]["properties"]["props"]["properties"]
        assert set(props) == {"open", "onOpenChange", "modifier"}
    current = schema["definitions"]["V_1_23_0_ModalBottomSheet"]["properties"]["props"][
        "properties"
    ]
    assert {"value", "onValueChange", "skipPartiallyExpanded"} <= set(current)
