"""Chat: a conversation shown as message bubbles, and the usual app around one.

Messages are ``{"role": "user" | "assistant", "content": str}``, the shape chat
model APIs take, so a function can pass the history straight to one.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from typing import TYPE_CHECKING, Any

from pycompose import ui
from pycompose.blocks.app import Blocks
from pycompose.blocks.components import Button, Component
from pycompose.blocks.text import Textbox
from pycompose.ui import CardWithoutOnClick, Modifier, Text, ThemeColor, cardColors

if TYPE_CHECKING:
    from pycompose.blocks.screen import View
    from pycompose.model.nodes.node import Node

__all__ = ["ChatInterface", "Chatbot"]

Message = dict[str, str]
ROLES = ("user", "assistant")


class Chatbot(Component):
    """A conversation, newest message last.

    Args:
        value: The messages it starts with.
        label: What it is called on screen.
        visible: Whether it is drawn.
    """

    def __init__(
        self,
        value: list[Message] | None = None,
        *,
        label: str = "",
        visible: bool = True,
    ) -> None:
        super().__init__(value, label=label, visible=visible, interactive=False)

    def to_python(self, raw: Any) -> list[Message]:
        """Hand an event its own copy of the messages.

        Args:
            raw: The held messages.

        Returns:
            Copies, so changing them changes nothing on screen.
        """
        return [dict(message) for message in raw]

    def to_raw(self, value: Any) -> list[Message]:
        """Hold messages, checking each has a known role and text.

        Args:
            value: The messages, or None for none.

        Returns:
            Copies of them.

        Raises:
            ValueError: If one is not a user or assistant message with text.
        """
        messages = []
        for message in value or ():
            if not (
                isinstance(message, Mapping)
                and message.get("role") in ROLES
                and isinstance(message.get("content"), str)
            ):
                raise ValueError(
                    'a chat message is {"role": "user" or "assistant", "content": text}'
                )
            messages.append({"role": message["role"], "content": message["content"]})
        return messages

    def draw(self, view: View) -> Node:
        """Draw each message as a bubble, the user's on the right.

        Args:
            view: The state being drawn.

        Returns:
            A native Column.
        """
        return ui.Column(
            id=self.id,
            modifier=Modifier().fill_max_width(),
            children=[
                *([Text(text=self.label, style="titleSmall")] if self.label else []),
                *(_bubble(i, message) for i, message in enumerate(view.value(self))),
            ],
        )


def _bubble(index: int, message: Message) -> Node:
    """One message, aligned and coloured by who sent it."""
    mine = message["role"] == "user"
    return ui.Column(
        id=f"m{index}",
        modifier=Modifier().fill_max_width().padding(vertical=4),
        horizontal_alignment="end" if mine else "start",
        children=[
            CardWithoutOnClick(
                modifier=Modifier().fill_max_width(0.85),
                colors=cardColors(
                    container_color=ThemeColor(
                        "primaryContainer" if mine else "surfaceContainerHigh"
                    )
                ),
                children=[
                    Text(
                        # An empty reply is one still being written.
                        text=message["content"] or "…",
                        modifier=Modifier().padding(12),
                    )
                ],
            )
        ],
    )


def ChatInterface(  # noqa: N802 -- reads as the class of app it builds
    fn: Callable[..., Any],
    *,
    placeholder: str = "Message",
    submit: str = "Send",
) -> Blocks:
    """Build the usual chat app around one function.

    ``fn(message, history)`` receives the new message and the messages before
    it, and returns the reply; one that yields streams it, each value the whole
    reply so far.

    Args:
        fn: Answers a message.
        placeholder: What the message field shows while empty.
        submit: What the send button says.

    Returns:
        The app.
    """
    with Blocks() as app:
        chat = Chatbot()
        message = Textbox(placeholder=placeholder)
        Button(submit).click(
            _respond(fn), inputs=[message, chat], outputs=[message, chat]
        )
    return app


def _asked(message: str, history: list[Message]) -> list[Message]:
    """The history with the new message and an empty reply to fill."""
    return [
        *history,
        {"role": "user", "content": message},
        {"role": "assistant", "content": ""},
    ]


def _respond(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap ``fn`` so the field clears, the message shows, then the reply streams.

    The wrapper keeps ``fn``'s kind: an ``async`` one stays on the loop, any
    other runs on the I/O pool.
    """
    if inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn):

        async def respond_async(
            message: str, history: list[Message]
        ) -> AsyncIterator[tuple[str, list[Message]]]:
            if not message.strip():
                return
            asked = _asked(message, history)
            yield "", asked
            reply = fn(message, history)
            if inspect.isawaitable(reply):
                yield "", [*asked[:-1], {"role": "assistant", "content": await reply}]
                return
            async for text in reply:
                yield "", [*asked[:-1], {"role": "assistant", "content": text}]

        return respond_async

    def respond(
        message: str, history: list[Message]
    ) -> Iterator[tuple[str, list[Message]]]:
        if not message.strip():
            return
        asked = _asked(message, history)
        yield "", asked
        reply = fn(message, history)
        for text in reply if inspect.isgenerator(reply) else (reply,):
            yield "", [*asked[:-1], {"role": "assistant", "content": text}]

    return respond
