"""Smoke-test the built wheel: emit, compose, and ship every golden.

CI used to run this as an inline heredoc in ``.github/workflows/ci.yml``. It is a
tool, not a workflow fragment, so it lives here where it can be reviewed, run and
reused. It must be executed with the wheel on ``sys.path`` ahead of the source
tree -- ``python -I - tools/wheel_smoke.py <wheel-dir>`` -- because its whole
purpose is to exercise the packaged code an installed user gets, not the checkout
beside it.

The golden check is a relation, not a list: whatever ``golden_names`` derives from
the packaged fixture directory must be readable through ``read_golden`` and must
byte-match the source fixture. Adding a golden therefore extends the set on both
sides at once; nothing here enumerates names that would then rot.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _add_wheel(wheel_dir: Path) -> Path:
    """Put the built wheel first on ``sys.path`` so packaging gaps surface.

    Args:
        wheel_dir: Directory holding the freshly built ``pycompose-*.whl``.

    Returns:
        The resolved wheel path.

    Raises:
        SystemExit: If the directory holds no wheel to test.
    """
    wheels = sorted(wheel_dir.glob("pycompose-*.whl"))
    if not wheels:
        raise SystemExit(f"no pycompose wheel in {wheel_dir}")
    sys.path.insert(0, str(wheels[0]))
    return wheels[0]


def _smoke_emit_and_compose() -> None:
    """Prove emit, composable and Component resolution all work from the wheel."""
    from pycompose import composable
    from pycompose.ir import emit_ir
    from pycompose.m3 import Column, Text
    from pycompose.state import State

    assert Column(id="screen", children=[Text(id="title", text="Hello")]).type == (
        "Column"
    )

    @composable
    def greeting(*, text: str) -> Text:
        return Text(id="message", text=text)

    composed = emit_ir(State(root=greeting(id="greeting", text="Hello")), "1.0.0")
    assert composed.root.type == "Text"
    assert composed.root.props["text"] == "Hello"


def _smoke_goldens(wheel: Path) -> None:
    """Every derived golden must be readable and byte-match the source fixture.

    Args:
        wheel: The wheel under test, kept only for the drift message.
    """
    from pycompose.ir import emit_ir, to_json_bytes
    from pycompose.state import State
    from pycompose.testing.helpers import (
        component_screen,
        golden_names,
        read_golden,
    )

    names = golden_names()
    assert names, "the wheel packaged no golden fixtures at all"

    source_dir = ROOT / "pycompose" / "testing" / "fixtures"
    source_names = tuple(sorted(p.name for p in source_dir.glob("*.json")))
    assert names == source_names, (
        f"wheel goldens {names} != source fixtures {source_names}; "
        f"{wheel.name} shipped a stale fixture directory"
    )

    for name in names:
        assert read_golden(name), f"golden {name} is empty"

    # The canonical-wire contract: emitting the screen matches its golden bytes.
    assert to_json_bytes(emit_ir(State(root=component_screen()), "1.0.0")) == (
        read_golden("component_screen.json")
    )


def main(argv: list[str]) -> int:
    """Run the wheel smoke checks.

    Args:
        argv: Command line, with the wheel directory as the sole argument.

    Returns:
        Process exit code: 0 on success, 1 if a check failed.
    """
    if len(argv) != 2:
        print("usage: wheel_smoke.py <wheel-dir>", file=sys.stderr)
        return 2
    wheel = _add_wheel(Path(argv[1]))
    _smoke_emit_and_compose()
    _smoke_goldens(wheel)
    print(f"wheel smoke passed: {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
