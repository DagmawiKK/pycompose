"""Per-pass results of unchanged subtrees and values, kept while the same one recurs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pycompose.core.expansion import ExpansionMemo

V = TypeVar("V")


class SubtreeMemo(Generic[V]):
    """One pass's result per frozen object, reused while the same object recurs.

    Frozen nodes make identity a sound key: an unchanged subtree is the same
    object, and its result is a pure function of it and the pass's inputs. Each
    pass keeps exactly the entries it used, so the memo is bounded by the tree it
    last saw; an entry holds its node, so the id cannot be reused by another.
    """

    __slots__ = ("_current", "_previous")

    def __init__(self) -> None:
        """Start empty."""
        self._previous: dict[object, tuple[object, V]] = {}
        self._current: dict[object, tuple[object, V]] = {}

    def start(self) -> None:
        """Begin a pass: last pass's entries become the only reusable ones."""
        self._previous, self._current = self._current, {}

    def get(self, node: object, context: object = None) -> V | None:
        """Return the result recorded for this exact subtree, keeping it alive.

        Args:
            node: The frozen subtree or value.
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

    def put(self, node: object, value: V, context: object = None) -> None:
        """Record this pass's result for a subtree.

        Args:
            node: The frozen subtree or value.
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
        bindings: Parsed binding specs, by frozen contract and binding id.
    """

    expansion: ExpansionMemo = field(default_factory=ExpansionMemo)
    emitted: SubtreeMemo[Any] = field(default_factory=SubtreeMemo)
    validated: SubtreeMemo[Any] = field(default_factory=SubtreeMemo)
    serialized: SubtreeMemo[bytes] = field(default_factory=SubtreeMemo)
    bindings: SubtreeMemo[Any] = field(default_factory=SubtreeMemo)
