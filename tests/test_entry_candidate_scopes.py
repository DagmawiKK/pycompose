"""Scope receivers and schema aliases in candidate derivation."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_classpath_dump import type_doc
from test_entry_candidates import catalog, modifier, plan, synthetic

from pycompose.compiler.candidate_props import CandidateError
from pycompose.compiler.entry_candidates import derive


def test_a_scope_extension_derives_the_scope_it_composes_in(tmp_path: Path) -> None:
    """A receiver the pin names is part of the wire face, not a review note."""
    receiver = type_doc(
        "androidx/compose/material3/SingleChoiceSegmentedButtonRowScope"
    )
    found = synthetic(tmp_path, receiver=receiver)
    item = derive(
        plan({"modifier": modifier()}, receiver=receiver),
        found.declarations[0],
        catalog(),
        {"category": "test", "stability": "stable"},
    )
    assert (
        item.entry["scope"]
        == "androidx.compose.material3.SingleChoiceSegmentedButtonRowScope"
    )
    scope = "androidx.compose.material3.SingleChoiceSegmentedButtonRowScope"
    assert f"receiver: composes only inside {scope}" in item.review


def test_a_schema_alias_keeps_the_native_identity(tmp_path: Path) -> None:
    """A distinct schema name may select one overload of a shared native name."""
    found = synthetic(tmp_path)
    item = derive(
        plan({"modifier": modifier()}),
        found.declarations[0],
        catalog(),
        {
            "category": "test",
            "stability": "stable",
            "nativeName": "Widget",
        },
        schema_name="AliasedWidget",
    )
    assert item.name == "AliasedWidget"
    assert item.entry["source"]["name"] == "Widget"

    with pytest.raises(CandidateError, match="does not match"):
        derive(
            plan({"modifier": modifier()}),
            found.declarations[0],
            catalog(),
            {
                "category": "test",
                "stability": "stable",
                "nativeName": "Other",
            },
            schema_name="AliasedWidget",
        )
