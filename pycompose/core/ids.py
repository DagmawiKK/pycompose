"""Deterministic, parent-path-based node ids with collision detection.

A node's id is its parent's id plus its key among its siblings: its explicit
id, else the call site that declared it (never random, never its position), so
the same tree always yields byte-identical ids across rebuilds and a node keeps
its identity when a conditional before it appears or disappears.
:class:`IdRegistry` collects the ids claimed in one snapshot and rejects
duplicates with node context.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Collection, Sequence
from types import CodeType
from typing import Final

from pycompose.core.node import Node
from pycompose.errors import IrError

__all__ = [
    "ROOT_ID",
    "IdRegistry",
    "call_site",
    "child_id",
    "id_path",
    "make_path_id",
    "sibling_keys",
]

#: The id of the snapshot's root node.
ROOT_ID: Final[str] = "root"

_SEPARATOR: Final[str] = "."


def make_path_id(path: Sequence[str | int]) -> str:
    """Join ``path`` segments into a deterministic node id.

    Args:
        path: The ordered path segments from the root to the node.

    Returns:
        The ``'.'``-joined id.

    Raises:
        IrError: If ``path`` is empty.
    """
    if not path:
        raise IrError("node id path must not be empty")
    return _SEPARATOR.join(str(segment) for segment in path)


def child_id(parent_id: str, key: str | int) -> str:
    """Return the id of a child at ``key`` under ``parent_id``.

    Args:
        parent_id: The parent node id.
        key: The child's stable key (index or explicit key).

    Returns:
        The deterministic child id.
    """
    return f"{parent_id}{_SEPARATOR}{key}"


def call_site(depth: int, skip: Collection[CodeType] = ()) -> str:
    """Name the line of code that is declaring a node.

    The name is the declaring function, its line and its bytecode offset, so
    two declarations on one line differ and the same declaration names the
    same site on every run of the same code.

    Args:
        depth: Frames between the caller of this function and the declaration.
        skip: Constructor code objects to step over, so a subclass chain names
            the app's line rather than its own ``__init__``.

    Returns:
        A sibling key free of the id separator.
    """
    frame = sys._getframe(depth + 1)
    while frame.f_code in skip and frame.f_back is not None:
        frame = frame.f_back
    code = frame.f_code
    name = code.co_qualname.replace(_SEPARATOR, "/")
    return f"{name}:{frame.f_lineno}:{frame.f_lasti}"


def sibling_keys(children: Sequence[Node]) -> tuple[tuple[str | int, bool], ...]:
    """Key each child among its siblings.

    An explicit id is its own key. A node with no id is keyed by its call site;
    a site that declares several siblings (a loop) numbers them in order, as
    Compose does for a call site without a key, and reports that it repeats.
    A node with neither falls back to its position.

    Args:
        children: One parent's children in order.

    Returns:
        Per child, its key and whether that key came from a repeated site.
    """
    counts = Counter(child.site for child in children if not child.id and child.site)
    seen: Counter[str] = Counter()
    keys: list[tuple[str | int, bool]] = []
    for index, child in enumerate(children):
        if child.id:
            keys.append((child.id, False))
        elif child.site and counts[child.site] == 1:
            keys.append((child.site, False))
        elif child.site:
            keys.append((f"{child.site}#{seen[child.site]}", True))
            seen[child.site] += 1
        else:
            keys.append((index, False))
    return tuple(keys)


def id_path(node_id: str) -> tuple[str, ...]:
    """Split a node id back into its path segments.

    Args:
        node_id: A node id produced by :func:`make_path_id`.

    Returns:
        The path segments.
    """
    return tuple(node_id.split(_SEPARATOR))


class IdRegistry:
    """Collects node ids in one snapshot and rejects collisions."""

    __slots__ = ("_claimed",)

    def __init__(self) -> None:
        """Create an empty registry."""
        self._claimed: set[str] = set()

    def claim(
        self,
        node_id: str,
        *,
        node_type: str,
        path: tuple[str, ...] | None = None,
    ) -> str:
        """Claim ``node_id`` for a node.

        Args:
            node_id: The candidate id.
            node_type: The component type (error context).
            path: The node's path segments; defaults to ``id_path(node_id)``.

        Returns:
            ``node_id`` unchanged.

        Raises:
            IrError: If ``node_id`` was already claimed.
        """
        if node_id in self._claimed:
            raise IrError(
                "duplicate node id",
                node_id=node_id,
                node_type=node_type,
                path=id_path(node_id) if path is None else path,
            )
        self._claimed.add(node_id)
        return node_id

    def __contains__(self, node_id: object) -> bool:
        """Report whether ``node_id`` has been claimed.

        Args:
            node_id: The candidate id.

        Returns:
            ``True`` when the id is claimed.
        """
        return isinstance(node_id, str) and node_id in self._claimed

    def __len__(self) -> int:
        """Return the number of claimed ids.

        Returns:
            The claimed-id count.
        """
        return len(self._claimed)
