"""Optional IDE signatures through the installed CLI and a type checker."""

import os
import subprocess
import sys
from pathlib import Path


def test_cli_generates_typed_composable_stubs_without_executing_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "header.py"
    source.write_text(
        "from pycompose import composable\n"
        "from pycompose.material3 import Text\n"
        'raise RuntimeError("must not run")\n'
        "@composable\n"
        "def ProfileHeader(*, name: str):\n"
        '    return Text(id="name", text=name)\n'
    )
    generated = subprocess.run(
        [sys.executable, "-m", "pycompose_cli", "stubs", str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert generated.returncode == 0, generated.stderr
    source.with_suffix(".pyi").write_text(generated.stdout)
    client = tmp_path / "client.py"
    client.write_text(
        "from header import ProfileHeader\n"
        "from pycompose.core import Node\n"
        'node: Node = ProfileHeader(id="profile", name="Ada")\n'
    )
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", "--no-incremental", str(client)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "MYPYPATH": str(Path(__file__).parents[1])},
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    client.write_text(
        'from header import ProfileHeader\nProfileHeader(id="profile", name=42)\n'
    )
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", "--no-incremental", str(client)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "MYPYPATH": str(Path(__file__).parents[1])},
        check=False,
    )
    assert result.returncode != 0
    assert 'Argument "name"' in result.stdout


def test_composable_runtime_signature_exposes_the_instance_key() -> None:
    import inspect

    from pycompose import composable
    from pycompose.core import Node
    from pycompose.material3 import Text

    @composable
    def greeting(*, text: str = "Hello") -> Node:
        return Text(id="text", text=text)

    signature = inspect.signature(greeting)
    assert signature.parameters["id"].kind == inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["id"].default is None
    assert signature.parameters["text"].annotation is str
    assert signature.parameters["text"].default == "Hello"
    assert signature.return_annotation is Node


def test_expansion_failures_name_the_composable_source_and_instance() -> None:
    import pytest

    from pycompose import composable
    from pycompose.errors import IrValidationError
    from pycompose.material3 import Text
    from pycompose.ui.composition import expand

    @composable
    def broken():
        return Text(id="text", text="Hello", style="wrong")

    with pytest.raises(IrValidationError) as exc:
        expand(broken(id="profile"))
    assert exc.value.context["node_id"] == "profile"
    assert "broken" in exc.value.context["source"]
    assert "test_composable_stubs.py:" in exc.value.context["source"]
    assert exc.value.__cause__ is not None


def test_cyclic_input_containers_fail_with_composable_context() -> None:
    import pytest

    from pycompose import composable
    from pycompose.errors import IrValidationError
    from pycompose.material3 import Text

    @composable
    def greeting(*, values):
        return Text(id="text", text=str(values))

    values = []
    values.append(values)
    with pytest.raises(IrValidationError) as exc:
        greeting(id="profile", values=values)
    assert exc.value.context["node_id"] == "profile"
    assert "greeting" in exc.value.context["source"]
