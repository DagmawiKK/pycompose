"""Deterministic, parent-path-based node ids with collision detection.

Ids derive from a node's position in the tree (never random), so the same tree
always yields byte-identical ids across rebuilds. :class:`IdRegistry` collects
the ids claimed in one snapshot and rejects duplicates with node context.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pycompose.errors import IrError

__all__ = ["ROOT_ID", "IdRegistry", "child_id", "id_path", "make_path_id"]

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
    return make_path_id((*id_path(parent_id), key))


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
        self._claimed: dict[str, tuple[str, tuple[str, ...]]] = {}

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
        resolved_path = id_path(node_id) if path is None else path
        if node_id in self._claimed:
            raise IrError(
                "duplicate node id",
                node_id=node_id,
                node_type=node_type,
                path=resolved_path,
            )
        self._claimed[node_id] = (node_type, resolved_path)
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
