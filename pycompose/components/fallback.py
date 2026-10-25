"""A component's stand-in on a host that cannot render it (ADR-0050)."""

from __future__ import annotations

from collections.abc import Callable

from pycompose.core.expansion import DeferredNode
from pycompose.core.ids import call_site
from pycompose.core.node import Node
from pycompose.ir.host import current_host


class Fallback(DeferredNode):
    """``Fallback(MapView(...), otherwise=Text("Map unavailable"))``.

    It composes ``content`` where the host can render every component in it,
    and ``otherwise`` where the host lacks one: an extension a stock dev client
    does not carry, or a component newer than the host's schema. The two are
    keyed apart, so neither inherits the other's native state. It is built on
    every pass, since the host is not one of its inputs.
    """

    __slots__ = ("content", "otherwise")
    memoized = False

    content: Node
    otherwise: Node

    def __init__(
        self, content: Node, *, otherwise: Node, id: str | None = None
    ) -> None:
        """Declare a component and what stands in for it.

        Args:
            content: What to compose where the host can render it.
            otherwise: What to compose where it cannot.
            id: Stable key, or None to key it by its call site.
        """
        site = "" if id else call_site(0, {Fallback.__init__.__code__})
        super().__init__(id=id or "", type="@fallback", site=site)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "otherwise", otherwise)

    @property
    def recursion_key(self) -> object:
        return (type(self), id(self))

    @property
    def source(self) -> str:
        return f"fallback for {self.content.type}"

    def build(self) -> tuple[Node, ...]:
        host = current_host()
        lacking = _lacking(self.content, host.lacks) if host is not None else None
        if host is None or not lacking:
            return (self.content,)
        host.substituted.update(lacking)
        return (self.otherwise,)


def _lacking(root: Node, lacks: Callable[[str], bool]) -> set[str]:
    """The component types in a native subtree the host lacks.

    Declarations inside are not built here; a fallback of their own covers
    what they produce.
    """
    found: set[str] = set()
    pending = [root]
    while pending:
        node = pending.pop()
        if isinstance(node, DeferredNode):
            continue
        if lacks(node.type):
            found.add(node.type)
        pending.extend(node.children)
    return found
