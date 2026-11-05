"""Draw functions: Python a Canvas runs on the host, checked before it draws."""

from __future__ import annotations

import json
import linecache
from math import cos, pi, sin

import pytest
from goldens import GOLDENS

from pycompose.errors import IrValidationError
from pycompose.host.wire import emit_ir, validate_ir
from pycompose.model.canonical import thaw_json
from pycompose.model.catalog.lock import SCHEMA_VERSION
from pycompose.model.catalog.vocabulary import DRAW_LIMITS
from pycompose.model.programs.drawing import validate_drawing
from pycompose.model.programs.recording import drawn
from pycompose.model.programs.refs import program_hash
from pycompose.model.snapshot import Snapshot
from pycompose.ui import Canvas, circle, host, line, rect, round_rect

PURPLE = 0xFF6750A4


@host
def dial(width: float, height: float) -> None:
    """A frame, and twelve marks around the middle, every third one larger."""
    rect(0x1F000000, 0, 0, width, height, stroke=2)
    for i in range(12):
        angle = i * pi / 6
        x = width / 2 + cos(angle) * 40
        y = height / 2 + sin(angle) * 40
        if i % 3 == 0:
            circle(PURPLE, 8, x, y)
        else:
            circle(PURPLE, 4, x, y, alpha=0.5)


@host
def bars(width: float, height: float) -> None:
    for row in range(3):
        for column in range(4):
            round_rect(
                0xFF00897B,
                column * width / 4,
                row * height / 3,
                width / 4 - 2,
                height / 3 - 2,
                corner_radius_x=4,
                corner_radius_y=4,
            )
    line(0xFF000000, 0, height, width, 0, stroke_width=1.5)


@host
def gauge(width: float, height: float, level: float, warn: bool, ticks: int) -> None:
    """A track, filled to the level the app binds; red past its warning."""
    rect(0x1F000000, 0, 0, width, height)
    rect(0xFFB3261E if warn else PURPLE, 0, 0, width * level, height)
    for i in range(10):
        if i < ticks:
            line(0xFF000000, width * i / 10, 0, width * i / 10, height / 4, 1)


CALLS = {
    "dial": (dial, [[100.0, 80.0], [48.0, 48.0]]),
    "bars": (bars, [[120.0, 90.0]]),
    "gauge": (gauge.bind(0.25, True, 4), [[200.0, 20.0]]),
}


def _golden() -> list[dict[str, object]]:
    # "program" is what a canvas's draw prop carries: a drawing, or one bound.
    return [
        {
            "name": name,
            "program": function.to_wire(),
            "frames": [
                {
                    "size": size,
                    "draws": [[c, list(a)] for c, a in drawn(function, *size)],
                }
                for size in sizes
            ],
        }
        for name, (function, sizes) in CALLS.items()
    ]


def test_drawings_and_their_python_draws_match_the_golden_the_host_runs() -> None:
    # The Kotlin evaluator runs the same file: each frame must draw what Python drew.
    path = GOLDENS / "programs" / "drawings.json"
    written = json.dumps(_golden(), indent=1, sort_keys=True) + "\n"
    assert path.read_text(encoding="utf-8") == written


def test_a_draw_function_compiles_to_a_draw_program() -> None:
    program = dial.to_wire()
    assert program["result"] == "draw"
    assert program["params"] == ["number", "number"]
    assert validate_drawing(program).result == "draw"


def test_a_canvas_carries_its_draw_function_to_the_host() -> None:
    node = Canvas(content_description="A dial", on_draw=dial)
    snapshot = emit_ir(Snapshot(root=node), SCHEMA_VERSION)
    assert validate_ir(snapshot).snapshot is snapshot
    name = program_hash(dial.to_wire())
    assert thaw_json(snapshot.root.props.get("onDraw")) == {"type": "ref", "hash": name}
    assert thaw_json((snapshot.metadata or {})["programs"]) == {name: dial.to_wire()}


@host
def half(width: float, height: float) -> float:
    return (width + height) / 2


def test_a_canvas_refuses_a_function_that_gives_a_value() -> None:
    with pytest.raises(IrValidationError):
        emit_ir(Snapshot(root=Canvas(on_draw=half)), SCHEMA_VERSION)


def test_a_canvas_carries_a_drawing_with_its_bound_arguments() -> None:
    node = Canvas(on_draw=gauge.bind(1, False, 10))
    snapshot = emit_ir(Snapshot(root=node), SCHEMA_VERSION)
    assert validate_ir(snapshot).snapshot is snapshot
    assert thaw_json(snapshot.root.props.get("onDraw")) == {
        "type": "bound",
        "program": {"type": "ref", "hash": program_hash(gauge.to_wire())},
        "args": [1.0, False, 10],
    }


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((0.5, True, 4, 9, 9, 9), "takes 5 arguments"),
        (("full", True, 4), "number parameter cannot take 'full'"),
        ((0.5, 1, 4), "boolean parameter cannot take 1"),
        ((0.5, True, 4.0), "integer parameter cannot take 4.0"),
        ((float("nan"), True, 4), "number parameter cannot take nan"),
    ],
)
def test_a_bound_argument_must_have_its_parameter_type(
    args: tuple[object, ...], message: str
) -> None:
    with pytest.raises(IrValidationError, match=message):
        gauge.bind(*args)


def test_a_canvas_refuses_a_drawing_left_unbound_or_bound_short() -> None:
    for drawing in (gauge, gauge.bind(False, 4)):
        with pytest.raises(IrValidationError):
            emit_ir(Snapshot(root=Canvas(on_draw=drawing)), SCHEMA_VERSION)


def test_a_draw_call_outside_a_draw_function_has_nothing_to_draw_on() -> None:
    with pytest.raises(RuntimeError, match="only inside a host draw function"):
        circle(PURPLE, 4, 0, 0)


def _refusal(body: str) -> SyntaxError:
    source = (
        "from pycompose.ui import circle, host\n"
        "@host\n"
        "def case(width: float, height: float) -> None:\n"
        f"{body}\n"
    )
    linecache.cache["<draw>"] = (len(source), None, source.splitlines(True), "<draw>")
    with pytest.raises(SyntaxError) as raised:
        exec(compile(source, "<draw>", "exec"), {})
    return raised.value


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("    circle(1, 4)", "circle needs center_x, center_y"),
        ("    print(1)", "print is no draw call"),
        ("    while True:\n        circle(1, 4, 0, 0)", "cannot use While"),
        (
            "    n = 3\n    for i in range(n):\n        circle(1, 4, 0, 0)",
            "cannot use For",
        ),
        ("    circle(1, 4, 0, 0, hue=2)", "no argument 'hue'"),
        ("    return", "cannot use Return"),
    ],
)
def test_what_a_draw_function_cannot_say_is_refused_with_its_line(
    body: str, message: str
) -> None:
    error = _refusal(body)
    assert message in error.msg
    assert error.lineno is not None and error.lineno >= 4


def test_a_frame_that_could_draw_too_much_is_refused() -> None:
    draw = {"draw": "circle", "args": [{"integer": 1}] + [{"number": 1.0}] * 5}
    inner = {"repeat": DRAW_LIMITS["repeat"], "body": [draw]}
    program = {
        "type": "program",
        "params": ["number", "number"],
        "result": "draw",
        "body": [
            {
                "repeat": DRAW_LIMITS["draws"] // DRAW_LIMITS["repeat"] + 1,
                "body": [inner],
            }
        ],
    }
    with pytest.raises(IrValidationError, match="more draws"):
        validate_drawing(program)


@pytest.mark.parametrize(
    "body",
    [
        [{"draw": "spiral", "args": []}],
        [{"draw": "circle", "args": [{"number": 1.0}] * 6}],
        [{"repeat": 2.5, "body": []}],
        [
            {
                "repeat": 2,
                "body": [
                    {"draw": "circle", "args": [{"loop": 1}] + [{"number": 1.0}] * 5}
                ],
            }
        ],
        [{"if": {"integer": 1}, "then": [], "else": []}],
    ],
)
def test_a_malformed_or_mistyped_drawing_is_refused(body: list[object]) -> None:
    program = {
        "type": "program",
        "params": ["number", "number"],
        "result": "draw",
        "body": body,
    }
    with pytest.raises(IrValidationError):
        validate_drawing(program)
