"""Candidate policy: event payload names and deprecated call plans.

The candidate tool names callback values consistently with the approved
catalog and never nominates a call plan the pin marks deprecated.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_entry_candidates import catalog, modifier, plan, synthetic

from tools.schema.candidate_props import CandidateError
from tools.schema.entry_candidates import derive, select


@pytest.mark.parametrize(
    ("callback", "field"),
    [("onCheckedChange", "value"), ("onExpandedChange", "expanded")],
)
def test_an_event_payload_gets_a_semantic_name(
    tmp_path: Path,
    callback: str,
    field: str,
) -> None:
    found = synthetic(tmp_path)
    parameters = {
        "modifier": modifier(),
        callback: {
            "policy": "event",
            "required": True,
            "payload": [{"name": "arg0", "type": "boolean"}],
        },
    }
    item = derive(
        plan(parameters),
        found.declarations[0],
        catalog(),
        {"category": "test", "stability": "stable"},
    )
    assert item.entry["props"][callback]["payload"] == [
        {"name": field, "type": "boolean"}
    ]


def test_an_unknown_event_payload_keeps_its_planner_name(tmp_path: Path) -> None:
    found = synthetic(tmp_path)
    parameters = {
        "modifier": modifier(),
        "onCustom": {
            "policy": "event",
            "required": True,
            "payload": [{"name": "arg0", "type": "string"}],
        },
    }
    item = derive(
        plan(parameters),
        found.declarations[0],
        catalog(),
        {"category": "test", "stability": "stable"},
    )
    assert item.entry["props"]["onCustom"]["payload"] == [
        {"name": "arg0", "type": "string"}
    ]


def test_select_refuses_a_deprecated_call_plan(tmp_path: Path) -> None:
    found = synthetic(tmp_path)
    deprecated = plan(
        {},
        annotations={
            "kotlin/Deprecated": {
                "message": "Replaced with NewWidget.",
                "level": "WARNING",
            }
        },
    )
    with pytest.raises(CandidateError, match="deprecated call plan.*NewWidget"):
        select({"candidates": [deprecated]}, found, "Widget")
