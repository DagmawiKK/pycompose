"""Samples are derived from types alone, so a new component or family needs none."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pycompose_cli import add
from pycompose_cli.project import Project
from pycompose_codegen.derive.samples import sample

from pycompose.contract.catalog import REGISTRY

ROOT = Path(__file__).resolve().parents[3]
LOCK = json.loads((ROOT / "schema/catalog.lock.json").read_text())


def _catalog(props: dict[str, Any]) -> dict[str, Any]:
    widget = {"props": props, "children": {"allowed": False}}
    return {**LOCK, "components": {**LOCK["components"], "Widget": widget}}


def test_a_required_value_of_any_family_is_sampled_from_its_definition() -> None:
    props = {
        "style": {"type": "value", "valueType": "TextStyle", "required": True},
        "range": {"type": "value", "valueType": "Range", "required": True},
        "shape": {"type": "value", "valueType": "Shape", "required": True},
    }
    sampled = sample(_catalog(props), "Widget")["root"]["props"]
    assert sampled["style"]["type"] == "TextStyle"
    # The n-th number of a value is n, so a range is never empty.
    assert (sampled["range"]["start"], sampled["range"]["end"]) == (0.0, 1.0)
    assert sampled["shape"]["type"] in LOCK["valueTypes"]


def test_a_family_with_no_sampleable_entry_is_named() -> None:
    props = {"thing": {"type": "value", "valueType": "Nothing", "required": True}}
    with pytest.raises(ValueError, match="no sample for value family Nothing"):
        sample(_catalog(props), "Widget")


@pytest.fixture
def registry() -> Iterator[None]:
    """The gate registers app components process-wide, as the CLI does once."""
    own, added = dict(REGISTRY._own), set(REGISTRY._added)
    yield
    REGISTRY._own.clear()
    REGISTRY._own.update(own)
    REGISTRY._added.clear()
    REGISTRY._added.update(added)


@pytest.mark.usefixtures("registry")
def test_the_render_gate_refuses_what_it_cannot_sample_or_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def render(_project: Project, snapshots: list[Path], out: Path) -> list[Path]:
        out.mkdir()
        for path in snapshots:
            reports = ["throws: no local colours"] if path.stem == "Broken" else []
            (out / f"{path.stem}.semantics.json").write_text(
                json.dumps({"windows": [], "reports": reports})
            )
        return []

    monkeypatch.setattr(add, "render", render)

    def component(text: dict[str, Any]) -> dict[str, Any]:
        return {
            "category": "app",
            "stability": "stable",
            "props": {"text": text},
            "children": {"allowed": False},
        }

    text = {"type": "string", "required": True}
    components = {
        "Fine": component(text),
        "Broken": component(text),
        "Unsampled": component(
            {"type": "value", "valueType": "Nothing", "required": True}
        ),
    }
    refused = add.render_gate(Project(root=tmp_path, config={}), components)
    assert refused["Broken"] == "renders with a report: throws: no local colours"
    assert refused["Unsampled"].endswith("no sample for value family Nothing")
    assert "Fine" not in refused
