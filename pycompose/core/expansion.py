"""Expand Python-only declarations before the IR pipeline sees native nodes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from pycompose.core.node import Node
from pycompose.errors import IrValidationError


class DeferredNode(Node, ABC):
    """Python-only declaration; never valid IR or a native registry entry."""

    __slots__ = ()

    @property
    @abstractmethod
    def recursion_key(self) -> object:
        """Return the definition identity used to detect recursive expansion."""

    @property
    @abstractmethod
    def source(self) -> str:
        """Return a human-readable definition location for diagnostics."""

    @abstractmethod
    def build(self) -> tuple[Node, ...]:
        """Evaluate this declaration on the caller's Python worker."""


@dataclass(slots=True)
class _Frame:
    node: Node
    prefix: str
    output: list[Node]
    children: list[Node] = field(default_factory=list)


class ExpansionMemo:
    """Reuse a deferred declaration's expansion while its inputs are unchanged.

    A composable's output is a pure function of its definition and arguments
    (the :class:`~pycompose.composition.Composable` contract). Arguments are
    keyed by value for scalars and by identity otherwise, so a structurally
    shared frozen State re-runs only the declarations whose inputs changed.
    Each pass keeps exactly the entries it used, which bounds the memo by the
    current tree and releases replaced inputs. With ``verify_every`` set, every
    n-th reuse is expanded again and compared, so a composable reading anything
    outside its arguments fails loudly instead of showing stale output.
    """

    def __init__(self, *, verify_every: int = 0) -> None:
        """Start empty.

        Args:
            verify_every: Re-expand and compare every n-th reuse; 0 never does.
        """
        self.verify_every = verify_every
        self._previous: dict[object, tuple[Node, tuple[Node, ...]]] = {}
        self._current: dict[object, tuple[Node, tuple[Node, ...]]] = {}
        self._reuses = 0

    def _start(self) -> None:
        self._previous, self._current = self._current, {}

    def _lookup(self, key: object) -> tuple[Node, ...] | None:
        entry = self._previous.get(key)
        if entry is None:
            return None
        self._current[key] = entry
        self._reuses += 1
        verify = self.verify_every and self._reuses % self.verify_every == 0
        return None if verify else entry[1]

    def _store(self, key: object, node: Node, produced: tuple[Node, ...]) -> None:
        cached = self._previous.get(key)
        if cached is not None and cached[1] != produced:
            raise IrValidationError(
                "composable output changed while its inputs did not; "
                "it reads something outside its arguments",
                node_id=node.id,
                source=node.source if isinstance(node, DeferredNode) else None,
            )
        # The entry holds the declaration, so its identity-keyed inputs stay
        # alive and their ids cannot be reused by unrelated objects.
        self._current[key] = (node, produced)


class _Expansion:
    def __init__(self) -> None:
        self.active: set[int] = set()
        self.definitions: set[object] = set()
        self.context: list[str] = []
        self.path: list[str] = []
        self.calls = 0

    def enter(self, frame: _Frame) -> tuple[Node, ...]:
        node = frame.node
        if id(node) in self.active:
            raise IrValidationError(
                "cyclic node graph",
                node_id=node.id,
                path=(*self.path, node.id),
            )
        self.active.add(id(node))
        self.path.append(node.id)
        if not isinstance(node, DeferredNode):
            return node.children
        if node.recursion_key in self.definitions:
            raise IrValidationError(
                "recursive composable",
                node_id=node.id,
                source=node.source,
                composition=tuple(self.context),
            )
        self.calls += 1
        if self.calls > 10000:
            raise IrValidationError("composition expansion limit exceeded")
        self.definitions.add(node.recursion_key)
        self.context.append(f"{node.id}: {node.source}")
        try:
            return node.build()
        except Exception as exc:
            raise IrValidationError(
                "composable expansion failed",
                node_id=node.id,
                source=node.source,
                composition=tuple(self.context),
                reason=str(exc),
            ) from exc

    def finish(self, frame: _Frame, memo: ExpansionMemo | None) -> None:
        node = frame.node
        self.active.remove(id(node))
        self.path.pop()
        if isinstance(node, DeferredNode):
            self.definitions.remove(node.recursion_key)
            self.context.pop()
            produced = tuple(
                child if node.slot is None else child.with_slot(node.slot)
                for child in frame.children
            )
            frame.output.extend(produced)
            if memo is not None:
                memo._store(_memo_key(frame), node, produced)
            return
        identity = f"{frame.prefix}.{node.id}" if frame.prefix and node.id else node.id
        unchanged = identity == node.id and len(frame.children) == len(node.children)
        unchanged = unchanged and all(
            left is right
            for left, right in zip(frame.children, node.children, strict=True)
        )
        result = (
            node
            if unchanged
            else Node(
                id=identity,
                type=node.type,
                props=node.props,
                children=frame.children,
                slot=node.slot,
            )
        )
        frame.output.append(result)


def _memo_key(frame: _Frame) -> object:
    node = frame.node
    assert isinstance(node, DeferredNode)
    return (frame.prefix, node.id, node.slot, node.recursion_key)


def expand_nodes(root: Node, memo: ExpansionMemo | None = None) -> Node:
    """Expand declarations iteratively, preserving untouched native branches.

    No context or function is retained in the result. Composable instance keys
    namespace their returned roots; ordinary descendant keys remain local for
    the emitter to qualify. Slot declarations may produce several siblings, and
    a deferred node filling a named slot passes it on to what it builds.

    Args:
        root: App declaration containing native nodes and deferred declarations.
        memo: The previous pass's expansions to reuse where inputs are
            unchanged; None expands everything.

    Returns:
        One native root with no deferred declarations anywhere beneath it.

    Raises:
        IrValidationError: If expansion fails, cycles, or does not yield one root.
    """
    output: list[Node] = []
    expansion = _Expansion()
    if memo is not None:
        memo._start()
    pending = [(_Frame(root, "", output), True)]
    while pending:
        frame, entering = pending.pop()
        if not entering:
            expansion.finish(frame, memo)
            continue
        if memo is not None and isinstance(frame.node, DeferredNode):
            reused = memo._lookup(_memo_key(frame))
            if reused is not None:
                frame.output.extend(reused)
                continue
        children = expansion.enter(frame)
        pending.append((frame, False))
        prefix = ""
        if isinstance(frame.node, DeferredNode):
            prefix = (
                f"{frame.prefix}.{frame.node.id}" if frame.prefix else frame.node.id
            )
        pending.extend(
            (_Frame(child, prefix, frame.children), True)
            for child in reversed(children)
        )
    if len(output) != 1:
        raise IrValidationError("composition must produce one root")
    return output[0]
