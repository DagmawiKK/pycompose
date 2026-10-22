"""Per-pass results of unchanged subtrees, kept while the same subtree recurs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pycompose.core.expansion import ExpansionMemo
from pycompose.core.node import Node

V = TypeVar("V")


class SubtreeMemo(Generic[V]):
    """One pass's result per subtree, reused while the same object is passed again.

    Frozen nodes make identity a sound key: an unchanged subtree is the same
    object, and its result is a pure function of it and the pass's inputs. Each
    pass keeps exactly the entries it used, so the memo is bounded by the tree it
    last saw; an entry holds its node, so the id cannot be reused by another.
    """

    __slots__ = ("_current", "_previous")

    def __init__(self) -> None:
        """Start empty."""
        self._previous: dict[object, tuple[Node, V]] = {}
        self._current: dict[object, tuple[Node, V]] = {}

    def start(self) -> None:
        """Begin a pass: last pass's entries become the only reusable ones."""
        self._previous, self._current = self._current, {}

    def get(self, node: Node, context: object = None) -> V | None:
        """Return the result recorded for this exact subtree, keeping it alive.

        Args:
            node: The subtree.
            context: Anything else the result depends on, compared by equality.

        Returns:
            The recorded result, or None.
        """
        key = (id(node), context)
        entry = self._previous.get(key) or self._current.get(key)
        if entry is None or entry[0] is not node:
            return None
        self._current[key] = entry
        return entry[1]

    def put(self, node: Node, value: V, context: object = None) -> None:
        """Record this pass's result for a subtree.

        Args:
            node: The subtree.
            value: Its result.
            context: Anything else the result depends on, compared by equality.
        """
        self._current[(id(node), context)] = (node, value)


@dataclass(slots=True)
class Reuse:
    """One publishing session's memo for every pass, from expansion to bytes.

    Attributes:
        expansion: Composable expansions, reused while their inputs are unchanged.
        emitted: Qualified, binding-lowered subtrees, by subtree and position.
        validated: Subtrees that passed validation, with every id they claim.
        serialized: Canonical bytes of emitted subtrees.
    """

    expansion: ExpansionMemo = field(default_factory=ExpansionMemo)
    emitted: SubtreeMemo[Any] = field(default_factory=SubtreeMemo)
    validated: SubtreeMemo[Any] = field(default_factory=SubtreeMemo)
    serialized: SubtreeMemo[bytes] = field(default_factory=SubtreeMemo)
