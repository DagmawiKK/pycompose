"""errors: PyComposeError carries structured context in its message."""

from __future__ import annotations

from pycompose.errors import IrError, PyComposeError


def test_error_without_context_is_just_the_message() -> None:
    assert str(PyComposeError("boom")) == "boom"


def test_error_without_message_renders_only_context() -> None:
    assert str(IrError(node_id="root")) == "node_id='root'"


def test_ir_error_appends_structured_context() -> None:
    error = IrError(
        "duplicate node id",
        node_id="root.0",
        node_type="Text",
        path=("root", "0"),
    )
    assert error.context == {
        "node_id": "root.0",
        "node_type": "Text",
        "path": ("root", "0"),
    }
    message = str(error)
    assert message.startswith("duplicate node id")
    assert "node_id='root.0'" in message
    assert "node_type='Text'" in message
    assert "path=('root', '0')" in message


def test_error_context_is_sorted_and_deterministic() -> None:
    first = str(IrError("x", b=2, a=1))
    second = str(IrError("x", a=1, b=2))
    assert first == second == "x (a=1, b=2)"
