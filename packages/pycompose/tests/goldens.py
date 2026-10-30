"""The wire goldens both languages test against, and the screen one is drawn from.

The goldens live in ``schema/goldens`` beside the catalog and the wire schema:
reviewed bytes, never regenerated, each change justified in its commit.
"""

from __future__ import annotations

from pathlib import Path

from pycompose.core import Node
from pycompose.foundation import Box, Column, LazyColumn, Row, Spacer
from pycompose.material3 import Button, Scaffold, Text, TextField
from pycompose.ui import Modifier

GOLDENS = Path(__file__).resolve().parents[3] / "schema" / "goldens"


def golden_names() -> tuple[str, ...]:
    """Every golden's file name, in order.

    Returns:
        The file names, sorted.
    """
    return tuple(sorted(path.name for path in GOLDENS.glob("*.json")))


def read_golden(name: str) -> bytes:
    """A golden's exact wire bytes, without its one terminal newline.

    Args:
        name: A name from :func:`golden_names`.

    Returns:
        The golden's bytes.

    Raises:
        ValueError: If ``name`` is not a golden.
    """
    if name not in golden_names():
        raise ValueError(f"unknown golden fixture: {name}")
    return (GOLDENS / name).read_bytes().removesuffix(b"\n")


def component_screen() -> Node:
    """The screen ``component_screen.json`` is the wire form of.

    Returns:
        A fresh screen with stable ids.
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
