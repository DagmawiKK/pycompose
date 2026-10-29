"""Display components: results to look at, written by events."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from pycompose import m3, media
from pycompose.blocks.components import Component
from pycompose.core.resources import valid_resource
from pycompose.extensions.environment import paths
from pycompose.m3 import FlowRow, LinearProgressIndicator, Modifier, Text
from pycompose.values import ContentScale

if TYPE_CHECKING:
    from pycompose.blocks.screen import View
    from pycompose.core.node import Node

__all__ = ["JSON", "Gallery", "Image", "Label"]

IMAGE_KINDS = ("drawable", "asset", "file")
THUMBNAIL = 112
"""A gallery picture's side, in dp."""


def _reference(value: Any) -> str:
    """An image prop's reference to a picture, saving one given as data."""
    if isinstance(value, str) and value.startswith("@"):
        if not valid_resource(value, IMAGE_KINDS):
            raise ValueError(f"{value!r} names no image")
        return value
    return media.image(value)


def _readable(reference: str) -> str:
    """What an event reads for a picture: a media file's path, else its reference."""
    kind, _, name = reference[1:].partition("/")
    return str(paths().cache / media.MEDIA / name) if kind == "file" else reference


class Image(Component):
    """A picture: bytes, a file path, a PIL image, or an ``@drawable/`` reference.

    Args:
        value: The picture it starts with, or None for none.
        label: What it is called on screen; also its description for TalkBack.
        visible: Whether it is drawn.
    """

    def __init__(
        self, value: Any = None, *, label: str = "", visible: bool = True
    ) -> None:
        super().__init__(value, label=label, visible=visible, interactive=False)

    def to_python(self, raw: Any) -> str | None:
        """Hand an event the picture as a file it can open.

        Args:
            raw: The held reference, or empty.

        Returns:
            A media file's path, a resource reference, or None for no picture.
        """
        return _readable(raw) if raw else None

    def to_raw(self, value: Any) -> str:
        """Hold a picture by reference, saving one given as data.

        Args:
            value: The picture, or None for none.

        Returns:
            Its reference, or empty.
        """
        return "" if value is None or value == "" else _reference(value)

    def draw(self, view: View) -> Node:
        """Draw the label and the picture, full width.

        Args:
            view: The state being drawn.

        Returns:
            A native Column.
        """
        reference = view.value(self)
        return m3.Column(
            id=self.id,
            modifier=Modifier().fill_max_width(),
            children=[
                *([Text(text=self.label)] if self.label else []),
                *(
                    [
                        m3.Image(
                            resource=reference,
                            content_description=self.label or "Image",
                            # As wide as the screen allows, keeping its proportions.
                            content_scale=ContentScale("FillWidth"),
                            modifier=Modifier().fill_max_width(),
                        )
                    ]
                    if reference
                    else []
                ),
            ],
        )


class Gallery(Component):
    """Pictures in a grid that wraps to the screen's width.

    Args:
        value: The pictures it starts with.
        label: What it is called on screen.
        visible: Whether it is drawn.
    """

    def __init__(
        self,
        value: Sequence[Any] | None = None,
        *,
        label: str = "",
        visible: bool = True,
    ) -> None:
        super().__init__(value, label=label, visible=visible, interactive=False)

    def to_python(self, raw: Any) -> list[str]:
        """Hand an event the pictures as files it can open.

        Args:
            raw: The held references.

        Returns:
            One path or reference per picture.
        """
        return [_readable(reference) for reference in raw]

    def to_raw(self, value: Any) -> list[str]:
        """Hold pictures by reference, saving those given as data.

        Args:
            value: The pictures, or None for none.

        Returns:
            Their references.
        """
        return [_reference(item) for item in value or ()]

    def draw(self, view: View) -> Node:
        """Draw the label and the grid.

        Args:
            view: The state being drawn.

        Returns:
            A native Column.
        """
        return m3.Column(
            id=self.id,
            modifier=Modifier().fill_max_width(),
            children=[
                *([Text(text=self.label)] if self.label else []),
                FlowRow(
                    modifier=Modifier().fill_max_width(),
                    children=[
                        m3.Image(
                            id=f"p{i}",
                            resource=reference,
                            content_description=f"{self.label or 'Picture'} {i + 1}",
                            # Square tiles, cropped to fill, as a photo grid shows them.
                            content_scale=ContentScale("Crop"),
                            modifier=Modifier().padding(2).size(THUMBNAIL),
                        )
                        for i, reference in enumerate(view.value(self))
                    ],
                ),
            ],
        )


class Label(Component):
    """A classifier's answer: the top label, and the most likely ones as bars.

    Args:
        value: A label, or each label's confidence from 0 to 1.
        label: What it is called on screen.
        top: How many labels the bars show.
        visible: Whether it is drawn.
    """

    def __init__(
        self,
        value: str | Mapping[str, float] | None = None,
        *,
        label: str = "",
        top: int = 5,
        visible: bool = True,
    ) -> None:
        self.top = top
        super().__init__(value, label=label, visible=visible, interactive=False)

    def to_raw(self, value: Any) -> list[list[Any]]:
        """Hold the labels as ``[name, confidence]``, most likely first.

        Args:
            value: A label, each label's confidence, or None for none.

        Returns:
            The most likely labels, at most ``top`` of them.

        Raises:
            ValueError: If a confidence is outside 0 to 1.
        """
        if value is None:
            return []
        if isinstance(value, str):
            return [[value, 1.0]]
        ranked = sorted(
            ((str(k), float(v)) for k, v in value.items()), key=lambda kv: -kv[1]
        )
        if any(not 0 <= p <= 1 for _, p in ranked):
            raise ValueError("a confidence is between 0 and 1")
        return [[name, p] for name, p in ranked[: self.top]]

    def to_python(self, raw: Any) -> dict[str, float]:
        """Hand an event each label's confidence.

        Args:
            raw: The held labels.

        Returns:
            Confidence by label.
        """
        return dict(raw)

    def draw(self, view: View) -> Node:
        """Draw the top label large, then a bar per label.

        Args:
            view: The state being drawn.

        Returns:
            A native Column.
        """
        ranked = view.value(self)
        return m3.Column(
            id=self.id,
            modifier=Modifier().fill_max_width(),
            children=[
                *([Text(text=self.label)] if self.label else []),
                *([Text(text=ranked[0][0], style="headlineMedium")] if ranked else []),
                *(
                    m3.Column(
                        id=f"l{i}",
                        modifier=Modifier().fill_max_width().padding(vertical=4),
                        children=[
                            Text(text=f"{name}  {p:.0%}", style="bodyMedium"),
                            LinearProgressIndicator(
                                progress=p, modifier=Modifier().fill_max_width()
                            ),
                        ],
                    )
                    for i, (name, p) in enumerate(ranked)
                ),
            ],
        )


class JSON(Component):
    """Any JSON value, shown indented.

    Args:
        value: The value it starts with.
        label: What it is called on screen.
        visible: Whether it is drawn.
    """

    def __init__(
        self, value: Any = None, *, label: str = "", visible: bool = True
    ) -> None:
        super().__init__(value, label=label, visible=visible, interactive=False)

    def to_raw(self, value: Any) -> Any:
        """Hold a JSON value as JSON reads it back.

        Args:
            value: Anything ``json`` can write.

        Returns:
            The same value, in JSON's own types.
        """
        return json.loads(json.dumps(value))

    def draw(self, view: View) -> Node:
        """Draw the label and the indented value.

        Args:
            view: The state being drawn.

        Returns:
            A native Column.
        """
        return m3.Column(
            id=self.id,
            modifier=Modifier().fill_max_width(),
            children=[
                *([Text(text=self.label)] if self.label else []),
                Text(
                    text=json.dumps(view.value(self), indent=2, ensure_ascii=False),
                    style="bodySmall",
                ),
            ],
        )
