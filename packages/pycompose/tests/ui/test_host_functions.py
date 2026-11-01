"""Host functions: Python compiled to a program the host calls within a frame."""

from __future__ import annotations

import importlib
import json
import linecache
import py_compile
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from goldens import GOLDENS

from pycompose.errors import IrValidationError
from pycompose.host.wire import emit_ir, validate_ir
from pycompose.model.canonical import thaw_json
from pycompose.model.catalog.lock import SCHEMA_VERSION
from pycompose.model.catalog.vocabulary import FUNCTION_LIMITS
from pycompose.model.programs.functions import HostFunction, validate_function
from pycompose.model.snapshot import Snapshot
from pycompose.ui import DatePicker, SelectableDates, host
from pycompose.ui._sources import host_sources
from pycompose.ui._sources import main as sources_main

DAY_MS = 86_400_000


@host
def weekdays(utc_time_millis: int) -> bool:
    """Monday to Friday: 1 January 1970 was a Thursday."""
    day = utc_time_millis // DAY_MS
    return (day + 3) % 7 < 5


@host
def this_decade(year: int) -> bool:
    return 2020 <= year < 2030


@host
def eased(fraction: float, steps: int) -> float:
    if fraction <= 0:
        return 0
    stepped = min(fraction, 1.0) * steps
    return abs(stepped) / steps if steps != 0 else -fraction


@host
def floored(a: int, b: int) -> int:
    return a // b * 10 + a % b if b != 0 else -a


CALLS: dict[str, tuple[HostFunction, list[list[object]]]] = {
    "weekdays": (
        weekdays,
        [[0], [86_400_000 * 2], [86_400_000 * 4], [-1], [1_767_225_600_000]],
    ),
    "this_decade": (this_decade, [[2019], [2020], [2029], [2030]]),
    "eased": (eased, [[-0.5, 4], [0.25, 4], [3.0, 2], [0.5, 0]]),
    "floored": (floored, [[7, 2], [-7, 2], [7, -2], [5, 0]]),
}


def _golden() -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "program": function.to_wire(),
            "calls": [{"args": args, "result": function(*args)} for args in calls],
        }
        for name, (function, calls) in CALLS.items()
    ]


def test_programs_and_their_python_answers_match_the_golden_the_host_runs() -> None:
    # The Kotlin evaluator runs the same file: each program must give the
    # answer its Python gave.
    path = GOLDENS / "programs" / "functions.json"
    written = json.dumps(_golden(), indent=1, sort_keys=True) + "\n"
    assert path.read_text(encoding="utf-8") == written


def test_a_host_function_still_calls_as_python() -> None:
    assert weekdays(0) is True  # a Thursday
    assert weekdays(DAY_MS * 2) is False
    assert str(weekdays.signature) == "(integer) -> boolean"


def test_a_program_checks_on_both_sides_as_it_was_compiled() -> None:
    signature = validate_function(eased.to_wire())
    assert signature.params == ("number", "integer")
    assert signature.result == "number"


def _refusal(source: str) -> SyntaxError:
    scope: dict[str, object] = {"host": host, "TEXT": "no"}
    # The compiler reads a function's source; give the case one to read.
    linecache.cache["<case>"] = (len(source), None, source.splitlines(True), "<case>")
    with pytest.raises(SyntaxError) as raised:
        exec(compile(source, "<case>", "exec"), scope)
    return raised.value


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("    for _ in range(3):\n        pass\n    return True", "cannot use For"),
        ("    return len([]) > 0", "cannot call len"),
        ("    return x.real > 0", "cannot use Attribute"),
        ("    return TEXT == 'no'", "not an argument, a local or a number"),
        ("    y = 1\n    y = 2\n    return x > y", "assigned once"),
        ("    if x > 0:\n        return True", "returns on every path"),
        ("    return x", "gives an integer where a boolean is needed"),
        ("    return x // 1.5 > 0", "floorDiv does not take (number, number)"),
    ],
)
def test_what_a_host_function_cannot_say_is_refused_with_its_line(
    body: str, message: str
) -> None:
    error = _refusal(f"@host\ndef case(x: int) -> bool:\n{body}\n")
    assert message in error.msg
    assert error.lineno is not None and error.lineno >= 3


def test_a_host_function_needs_annotations() -> None:
    assert "annotate with int" in _refusal("@host\ndef f(x):\n    return x\n").msg
    assert (
        "annotate with int"
        in _refusal("@host\ndef f(x: str) -> int:\n    return 1\n").msg
    )


@pytest.mark.parametrize(
    "program",
    [
        {"type": "program", "params": ["string"], "result": "boolean", "body": {}},
        {"type": "program", "params": [], "result": "boolean", "body": {"integer": 1}},
        {"type": "program", "params": [], "result": "integer", "body": {"arg": 0}},
        {
            "type": "program",
            "params": [],
            "result": "integer",
            "body": {"integer": 2**63},
        },
        {"type": "program", "params": [], "result": "number", "body": {"number": True}},
        {
            "type": "program",
            "params": ["integer"],
            "result": "integer",
            "body": {"op": "loop", "args": [{"arg": 0}]},
        },
        {
            "type": "program",
            "params": ["integer", "number"],
            "result": "boolean",
            "body": {"op": "lt", "args": [{"arg": 0}, {"arg": 1}]},
        },
    ],
)
def test_a_malformed_or_mistyped_program_is_refused(program: object) -> None:
    with pytest.raises(IrValidationError):
        validate_function(program)


def test_a_program_past_its_limits_is_refused() -> None:
    body: dict[str, object] = {"arg": 0}
    for _ in range(FUNCTION_LIMITS["depth"]):
        body = {"op": "neg", "args": [body]}
    program = {
        "type": "program",
        "params": ["integer"],
        "result": "integer",
        "body": body,
    }
    with pytest.raises(IrValidationError, match="exceeds"):
        validate_function(program)


def test_constants_are_read_as_the_function_is_defined() -> None:
    assert weekdays.to_wire()["body"] == {
        "op": "lt",
        "args": [
            {
                "op": "mod",
                "args": [
                    {
                        "op": "plus",
                        "args": [
                            {
                                "op": "floorDiv",
                                "args": [{"arg": 0}, {"integer": DAY_MS}],
                            },
                            {"integer": 3},
                        ],
                    },
                    {"integer": 7},
                ],
            },
            {"integer": 5},
        ],
    }


def test_a_date_picker_carries_its_python_predicate_to_the_host() -> None:
    node = DatePicker(selectable_dates=SelectableDates(is_selectable_date=weekdays))
    snapshot = emit_ir(Snapshot(root=node), SCHEMA_VERSION)
    assert validate_ir(snapshot).snapshot is snapshot
    assert thaw_json(snapshot.root.props.get("selectableDates")) == {
        "type": "SelectableDates",
        "isSelectableDate": weekdays.to_wire(),
    }


def test_a_function_of_the_wrong_signature_is_refused_where_it_is_given() -> None:
    with pytest.raises(IrValidationError, match=r"\(number, integer\) -> number"):
        SelectableDates(is_selectable_year=eased)


APP = """\
from pycompose.ui import host
import pycompose.ui as ui

DAY = 86_400_000


@host
def weekdays(t: int) -> bool:
    return (t // DAY + 3) % 7 < 5


def before(limit: int):
    @ui.host
    def early(year: int) -> bool:
        return year < limit

    return early
"""


def _bytecode_only(root: Path, name: str, source: str) -> None:
    path = root / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    py_compile.compile(str(path), cfile=str(root / f"{name}.pyc"), doraise=True)
    path.unlink()


@pytest.fixture
def device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    # The app's directory as an APK carries it: bytecode, and the build's table.
    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    for name in ("shipped", "__pycompose_host__"):
        sys.modules.pop(name, None)


def test_the_build_keeps_each_host_definitions_source_by_module_and_line(
    tmp_path: Path,
) -> None:
    (tmp_path / "screens").mkdir()
    (tmp_path / "screens" / "__init__.py").write_text(APP, encoding="utf-8")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "skip.py").write_text(APP, encoding="utf-8")
    table = host_sources(tmp_path)
    assert set(table) == {"screens:7", "screens:13"}
    assert table["screens:13"]["source"].startswith("@ui.host\ndef early(")
    assert table["screens:7"]["file"] == "screens/__init__.py"


def test_a_bytecode_only_app_compiles_its_host_functions_from_the_build(
    device: Path,
) -> None:
    (device / "src").mkdir()
    (device / "src" / "shipped.py").write_text(APP, encoding="utf-8")
    sources_main([str(device / "src"), str(device / "__pycompose_host__.py")])
    _bytecode_only(device, "shipped", APP)
    shipped = importlib.import_module("shipped")
    assert shipped.weekdays.signature.result == "boolean"
    assert shipped.weekdays.body["op"] == "lt"
    # A closure binds its own captured value, as it would from source.
    early = shipped.before(2030)
    assert early.body["args"][1] == {"integer": 2030}
    assert early(2029) is True


def test_a_bytecode_only_app_without_the_build_says_how_to_get_it(
    device: Path,
) -> None:
    _bytecode_only(device, "shipped", APP)
    with pytest.raises(OSError, match="pycompose build"):
        importlib.import_module("shipped")


def test_a_stale_build_is_refused_rather_than_run(device: Path) -> None:
    (device / "src").mkdir()
    (device / "src" / "shipped.py").write_text(APP, encoding="utf-8")
    sources_main([str(device / "src"), str(device / "__pycompose_host__.py")])
    _bytecode_only(
        device,
        "shipped",
        APP.replace("def weekdays(t: int)", "def weekdays(u: int)").replace(
            "(t //", "(u //"
        ),
    )
    with pytest.raises(SyntaxError, match="rebuild"):
        importlib.import_module("shipped")
