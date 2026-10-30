"""Compose's own spellings work as aliases of the Python forms."""

from __future__ import annotations

import pytest

from pycompose.errors import IrValidationError
from pycompose.ui import Column, Modifier, Text


def test_a_modifier_chain_may_start_on_the_class_as_in_compose() -> None:
    assert (
        Modifier.padding(4).fill_max_width() == Modifier().padding(4).fill_max_width()
    )


def test_children_may_be_given_positionally_as_in_a_content_lambda() -> None:
    positional = Column(Text(text="a"), Text(text="b"))

    assert [child.props["text"] for child in positional.children] == ["a", "b"]


def test_children_given_both_ways_are_refused() -> None:
    with pytest.raises(IrValidationError, match="positionally and by name"):
        Column(Text(text="a"), children=[Text(text="b")])
