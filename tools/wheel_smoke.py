"""Smoke-test the built wheel: emit and compose from the packaged code.

CI used to run this as an inline heredoc in ``.github/workflows/ci.yml``. It is a
tool, not a workflow fragment, so it lives here where it can be reviewed, run and
reused. It must be executed with the wheel on ``sys.path`` ahead of the source
tree -- ``python -I - tools/wheel_smoke.py <wheel-dir>`` -- because its whole
purpose is to exercise the packaged code an installed user gets, not the checkout
beside it. The wire goldens are the test suite's (``schema/goldens``), not the
wheel's.
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
    from pycompose.foundation import Column
    from pycompose.material3 import Text
    from pycompose.model.snapshot import Snapshot
    from pycompose.wire import emit_ir

    assert Column(id="screen", children=[Text(id="title", text="Hello")]).type == (
        "Column"
    )

    @composable
    def greeting(*, text: str) -> Text:
        return Text(id="message", text=text)

    composed = emit_ir(Snapshot(root=greeting(id="greeting", text="Hello")), "1.0.0")
    assert composed.root.type == "Text"
    assert composed.root.props["text"] == "Hello"


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
    print(f"wheel smoke passed: {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
