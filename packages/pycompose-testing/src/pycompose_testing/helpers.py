"""Packaged goldens and a representative screen, independent of Android."""

from importlib.resources import files

from pycompose.core import Node
from pycompose.foundation import Box, Column, LazyColumn, Row, Spacer
from pycompose.material3 import Button, Scaffold, Text, TextField
from pycompose.ui import Modifier


def golden_names() -> tuple[str, ...]:
    """List every packaged JSON golden in deterministic filename order.

    Returns:
        Fixture filenames, including their .json suffix.
    """
    return tuple(
        sorted(
            resource.name
            for resource in files("pycompose_testing").joinpath("fixtures").iterdir()
            if resource.is_file() and resource.name.endswith(".json")
        )
    )


def read_golden(name: str) -> bytes:
    """Read exact canonical wire bytes, excluding one file terminal newline.

    Args:
        name: A filename returned by golden_names.

    Returns:
        Golden UTF-8 wire bytes; extra whitespace is not stripped.

    Raises:
        ValueError: If name does not identify a packaged golden.
    """
    if name not in golden_names():
        raise ValueError(f"unknown golden fixture: {name}")
    return (
        files("pycompose_testing")
        .joinpath("fixtures", name)
        .read_bytes()
        .removesuffix(b"\n")
    )


def component_screen() -> Node:
    """Build a screen with all nine initial components and five modifiers.

    Returns:
        Fresh immutable component nodes with explicit stable sibling keys.
    """
    return Scaffold(
        id="screen",
        content=Column(
            id="body",
            children=(
                Text(id="title", text="Hello PyCompose", style="titleLarge"),
                Row(
                    id="actions",
                    children=(
                        Button(
                            id="add", text="Add", on_click="increment", enabled=True
                        ),
                        Spacer(id="gap", modifier=Modifier().size(8)),
                    ),
                ),
                Box(
                    id="input",
                    children=(
                        TextField(
                            id="name",
                            value="Ada",
                            on_value_change="submit",
                            label="Name",
                        ),
                    ),
                ),
                LazyColumn(
                    id="items",
                    items=(Text(id="first", text="One"), Text(id="second", text="Two")),
                ),
            ),
        ),
        modifier=Modifier()
        .padding(16)
        .fill_max_width()
        .clip("rounded")
        .clickable("submit"),
    )
