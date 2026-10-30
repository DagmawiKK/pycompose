"""Write the wire corpus both validators must judge identically.

Python validates snapshots it emits; the host validates the bytes it receives.
They are two implementations of one contract, generated from one schema, and
nothing else proves they agree at the edges: number widths, empty children,
unknown fields. This tool emits one rich, valid snapshot and a set of
mutations of it, and records the Python verdict for each. The Kotlin
``CorpusTest`` reads the same files and must reach the same verdicts.

    python tools/corpus.py            # regenerate
    python tools/corpus.py --check    # fail if the committed corpus is stale
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pycompose_cli.commands.validate import validate_file

from pycompose.app import Intent
from pycompose.contract.catalog import SCHEMA_VERSION
from pycompose.core.effect import Effect
from pycompose.errors import PyComposeError
from pycompose.foundation import Column
from pycompose.material3 import Button, Scaffold, Switch, Text, TextField
from pycompose.state import State
from pycompose.ui import Modifier
from pycompose.wire import emit_ir, to_json

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "android/ir/src/test/resources/corpus"

Mutation = Callable[[dict[str, Any]], None]


class Edit(Intent):
    """Stands in for a text field's intent; the corpus is never dispatched."""

    value: str


class Flip(Intent):
    """Stands in for a switch's intent; the corpus is never dispatched."""

    value: bool


def base() -> dict[str, Any]:
    """Return one valid snapshot touching slots, bindings, effects and data.

    Returns:
        The snapshot as parsed JSON.
    """
    state = State(
        root=Scaffold(
            top_bar=Text(text="Corpus", style="titleLarge"),
            content=Column(
                modifier=Modifier.padding(8).fill_max_width(0.5),
                children=[
                    Text(text="Body"),
                    TextField(
                        value="draft", label="Name", selection=2, on_value_change=Edit
                    ),
                    Switch(checked=True, on_checked_change=Flip),
                    Button(text="Go", on_click=Flip(value=True)),
                ],
            ),
        ),
        effects=(Effect("toast", {"message": "saved"}),),
        data={"draft": "draft", "count": 2},
    )
    return json.loads(to_json(emit_ir(state, SCHEMA_VERSION)))


def _node(document: dict[str, Any], kind: str) -> dict[str, Any]:
    pending = [document["root"]]
    while pending:
        node = pending.pop()
        if node["type"] == kind:
            return node
        pending.extend(node.get("children", []))
    raise LookupError(kind)


def _set(kind: str, prop: str, value: object) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        _node(document, kind)["props"][prop] = value

    return mutate


def _drop(kind: str, prop: str) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        del _node(document, kind)["props"][prop]

    return mutate


def _top(key: str, value: object) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        if value is _DELETE:
            del document[key]
        else:
            document[key] = value

    return mutate


def _metadata(key: str, value: object) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        document["metadata"][key] = value

    return mutate


def _duplicate_id(document: dict[str, Any]) -> None:
    body = _node(document, "Column")
    body["children"][1]["id"] = body["children"][0]["id"]


def _unknown_type(document: dict[str, Any]) -> None:
    _node(document, "Text")["type"] = "NoSuchComponent"


def _unknown_slot(document: dict[str, Any]) -> None:
    for child in document["root"]["children"]:
        if child.get("slot") == "topBar":
            child["slot"] = "noSuchSlot"
            return
    raise LookupError("topBar")


def _children_object(document: dict[str, Any]) -> None:
    _node(document, "Column")["children"] = {"0": _node(document, "Switch")}


def _empty_id(document: dict[str, Any]) -> None:
    _node(document, "Switch")["id"] = ""


def _unknown_node_field(document: dict[str, Any]) -> None:
    _node(document, "Switch")["extra"] = True


_DELETE = object()


def _expression(argument: dict[str, Any]) -> dict[str, Any]:
    """A colour expression: black at the alpha the argument gives."""
    return {
        "type": "expression",
        "node": {"op": "alpha", "color": "#000000", "args": [argument]},
    }


MUTATIONS: dict[str, Mutation] = {
    "text_number": _set("Text", "text", 3),
    "text_null": _set("Text", "text", None),
    "selection_fraction": _set("TextField", "selection", 1.5),
    "selection_string": _set("TextField", "selection", "2"),
    "selection_huge": _set("TextField", "selection", 2**63),
    "style_unknown": _set("Text", "style", "titelLarge"),
    "unknown_prop": _set("Text", "fooBar", "x"),
    "checked_string": _set("Switch", "checked", "true"),
    "required_dropped": _drop("Button", "onClick"),
    "binding_undeclared": _set(
        "Button", "onClick", {"fields": {}, "intent": "app.nowhere.handler"}
    ),
    "props_array": _set("Switch", "props", []),
    "unknown_type": _unknown_type,
    "unknown_slot": _unknown_slot,
    "duplicate_id": _duplicate_id,
    "children_object": _children_object,
    "empty_id": _empty_id,
    "unknown_node_field": _unknown_node_field,
    "schema_future": _top("schemaVersion", "9.0.0"),
    "schema_malformed": _top("schemaVersion", "1.x"),
    "version_missing": _top("version", _DELETE),
    "root_missing": _top("root", _DELETE),
    "unknown_envelope_field": _top("extra", 1),
    "metadata_array": _top("metadata", []),
    "data_array": _metadata("data", [1]),
    "effects_object": _metadata("effects", {"kind": "toast"}),
    "effect_kind_unknown": _metadata("effects", [{"kind": "explode", "payload": {}}]),
    "intents_array": _metadata("intents", []),
    "echo_negative": _metadata("echoes", [{"seq": -1, "target": "increment"}]),
    "echo_string": _metadata("echoes", [{"seq": "1", "target": "increment"}]),
    "expression_literal": _set("Text", "color", _expression({"number": 0.5})),
    "expression_unknown_op": _set(
        "Text", "color", {"type": "expression", "node": {"op": "pow", "args": []}}
    ),
    "expression_stream_missing": _set(
        "Text", "color", _expression({"stream": "nowhere", "name": "progress"})
    ),
    "expression_number_prop": _set("Text", "text", _expression({"number": 1})),
}


def documents() -> dict[str, dict[str, Any]]:
    """Return the corpus: the valid base and every mutation of it.

    Returns:
        Documents by name.
    """
    valid = base()
    corpus = {"base": valid}
    for name, mutate in MUTATIONS.items():
        document = copy.deepcopy(valid)
        mutate(document)
        corpus[name] = document
    return corpus


def verdict(document: dict[str, Any]) -> bool:
    """Return whether the Python validator accepts a wire document.

    Args:
        document: The parsed document.

    Returns:
        True when it validates.
    """
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "snapshot.json"
        path.write_text(json.dumps(document))
        try:
            validate_file(path)
        except (PyComposeError, KeyError, TypeError, ValueError):
            return False
    return True


def render() -> dict[str, str]:
    """Return every corpus file's text, including the verdict index.

    Returns:
        File names to contents.
    """
    files: dict[str, str] = {}
    verdicts: dict[str, bool] = {}
    for name, document in documents().items():
        files[f"{name}.json"] = json.dumps(document, indent=1, sort_keys=True) + "\n"
        verdicts[name] = verdict(document)
    files["verdicts.json"] = json.dumps(verdicts, indent=1, sort_keys=True) + "\n"
    return files


def main() -> int:
    """Write or check the corpus.

    Returns:
        A process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    files = render()
    stale = [
        name
        for name, text in files.items()
        if not (CORPUS / name).is_file() or (CORPUS / name).read_text() != text
    ]
    if check:
        if stale:
            print(f"corpus.py: stale corpus files: {', '.join(stale)}", file=sys.stderr)
            return 1
        return 0
    CORPUS.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (CORPUS / name).write_text(text)
    print(f"corpus.py: wrote {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
