"""Depth-first node traversal with active-path cycle detection.

Visits occurrences, not unique objects: immutable subtrees may be shared. The
explicit iterator stack costs O(depth); error paths are materialized only on
failure. Consumers own their policy and post-order reconstruction.
"""

from collections.abc import Callable, Iterator

from pycompose.errors import IrValidationError
from pycompose.model.nodes.node import Node


class NodeCycleError(IrValidationError):
    """A node graph contains an ancestor cycle, not merely a shared subtree."""


def walk_nodes(
    root: Node, prune: Callable[[Node], bool] | None = None
) -> Iterator[tuple[Node, bool]]:
    """Visit each occurrence on entry (True) and exit (False), in child order.

    Args:
        root: Node whose descendants are visited.
        prune: Asked on entry; a node it accepts is entered and exited without
            visiting its descendants, for a pass that already has its result.

    Yields:
        tuple[Node, bool]: The node and whether this visit enters its subtree.

    Raises:
        NodeCycleError: If a descendant refers to an active ancestor.
    """
    stack: list[tuple[Node, Iterator[Node]]] = []
    active: set[int] = set()
    node = root
    while True:
        if id(node) in active:
            raise NodeCycleError(
                "cyclic node graph",
                node_id=node.id,
                node_type=node.type,
                path=(*(parent.id for parent, _ in stack), node.id),
            )
        active.add(id(node))
        pruned = prune is not None and prune(node)
        stack.append((node, iter(() if pruned else node.children)))
        yield node, True
        while stack:
            parent, children = stack[-1]
            try:
                node = next(children)
                break
            except StopIteration:
                stack.pop()
                active.remove(id(parent))
                yield parent, False
        else:
            return
