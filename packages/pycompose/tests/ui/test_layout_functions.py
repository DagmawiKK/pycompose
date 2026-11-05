"""Layout functions: Python a Layout runs on the host to place its children."""

from __future__ import annotations

import json
import linecache

import pytest
from goldens import GOLDENS

from pycompose.errors import IrValidationError
from pycompose.host.wire import emit_ir, validate_ir
from pycompose.model.catalog.lock import SCHEMA_VERSION
from pycompose.model.programs.layout import validate_layout
from pycompose.model.programs.recording import laid_out
from pycompose.model.snapshot import Snapshot
from pycompose.ui import (
    Layout,
    Size,
    Text,
    child_height,
    child_width,
    host,
    place,
)


@host
def column(max_width: float, max_height: float, count: int) -> Size:  # noqa: ARG001
    """Children one under another; as wide as the widest."""
    y = 0.0
    widest = 0.0
    for i in range(count):
        place(i, 0, y)
        y = y + child_height(i)
        widest = max(widest, child_width(i))
    return Size(widest, y)


@host
def flow(max_width: float, max_height: float, count: int, gap: float) -> Size:  # noqa: ARG001
    """Children in rows, wrapping where the next would pass the largest width."""
    x = 0.0
    y = 0.0
    row = 0.0
    for i in range(count):
        if x > 0 and x + child_width(i) > max_width:
            x = 0.0
            y = y + row + gap
            row = 0.0
        place(i, x, y)
        x = x + child_width(i) + gap
        row = max(row, child_height(i))
    return Size(max_width, y + row)


SIZES = [[80.0, 20.0], [120.0, 30.0], [60.0, 25.0], [90.0, 20.0]]
CALLS = {
    "column": (column, [[300.0, 800.0, SIZES], [300.0, 800.0, []]]),
    "flow": (flow.bind(8.0), [[220.0, 800.0, SIZES]]),
}


def _golden() -> list[dict[str, object]]:
    frames = []
    for name, (function, cases) in CALLS.items():
        entries = []
        for max_width, max_height, sizes in cases:
            size, placements = laid_out(
                function, max_width, max_height, [tuple(s) for s in sizes]
            )
            entries.append(
                {
                    "max": [max_width, max_height],
                    "sizes": sizes,
                    "size": list(size),
                    "placements": [list(p) for p in placements],
                }
            )
        frames.append({"name": name, "program": function.to_wire(), "frames": entries})
    return frames


def test_layouts_and_their_python_placements_match_the_golden_the_host_runs() -> None:
    # The Kotlin evaluator runs the same file: each frame must place as Python did.
    path = GOLDENS / "programs" / "layouts.json"
    written = json.dumps(_golden(), indent=1, sort_keys=True) + "\n"
    assert path.read_text(encoding="utf-8") == written


def test_a_layout_function_compiles_to_a_layout_program() -> None:
    program = column.to_wire()
    assert program["result"] == "layout"
    assert program["params"] == ["number", "number", "integer"]
    assert validate_layout(program).result == "layout"


def test_a_layout_carries_its_function_to_the_host() -> None:
    node = Layout(measure_policy=flow.bind(4.0), children=[Text(text="a")])
    snapshot = emit_ir(Snapshot(root=node), SCHEMA_VERSION)
    assert validate_ir(snapshot).snapshot is snapshot


def _refusal(body: str) -> SyntaxError:
    source = (
        "from pycompose.ui import Size, child_width, host, place\n"
        "@host\n"
        "def case(max_width: float, max_height: float, count: int) -> Size:\n"
        f"{body}\n"
    )
    linecache.cache["<layout>"] = (
        len(source),
        None,
        source.splitlines(True),
        "<layout>",
    )
    with pytest.raises(SyntaxError) as raised:
        exec(compile(source, "<layout>", "exec"), {})
    return raised.value


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("    place(0, 0, 0)", "ends by returning its Size"),
        (
            "    if count > 1:\n        return Size(1, 1)\n    return Size(0, 0)",
            "Return",
        ),
        (
            "    x = 1\n    x = 2.5\n    return Size(x, 0)",
            "gives a number where a integer",
        ),
        ("    max_width = 3.0\n    return Size(0, 0)", "is an argument"),
        (
            "    for i in range(count):\n        w = child_width(i)\n"
            "    return Size(w, 0)",
            "w",
        ),
        ("    print(1)\n    return Size(0, 0)", "calls place"),
    ],
)
def test_what_a_layout_function_cannot_say_is_refused_with_its_line(
    body: str, message: str
) -> None:
    error = _refusal(body)
    assert message in error.msg
    assert error.lineno is not None and error.lineno >= 4


@pytest.mark.parametrize(
    "body",
    [
        [
            {
                "call": "place",
                "args": [{"number": 1.0}, {"number": 0.0}, {"number": 0.0}],
            }
        ],
        [{"set": 0, "value": {"number": 1.0}}],
        [{"let": {"number": 1.0}}, {"set": 0, "value": {"integer": 1}}],
        [
            {"if": {"boolean": True}, "then": [{"let": {"number": 1.0}}], "else": []},
            {"call": "size", "args": [{"local": 0}, {"number": 0.0}]},
        ],
        [
            {
                "repeat": "children",
                "body": [
                    {
                        "repeat": "children",
                        "body": [
                            {"repeat": "children", "body": [{"repeat": 1, "body": []}]}
                        ],
                    }
                ],
            }
        ],
    ],
)
def test_a_malformed_or_mistyped_layout_is_refused(body: list[object]) -> None:
    program = {
        "type": "program",
        "params": ["number", "number", "integer"],
        "result": "layout",
        "body": body,
    }
    with pytest.raises(IrValidationError):
        validate_layout(program)
