"""Expand Python-only declarations before the IR pipeline sees native nodes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection, Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import ClassVar, NamedTuple

from pycompose.core.ids import sibling_keys
from pycompose.core.node import Node
from pycompose.core.reads import recording
from pycompose.errors import IrValidationError

Reads = tuple[tuple[str, str, object], ...]
"""Fields a build read: (argument, field, value), all of them tracked arguments."""


_building: ContextVar[str] = ContextVar("building", default="")
"""The path of the composable instance whose declaration is being built."""


def building_path() -> str:
    """Return the instance path a declaration is being built under.

    Returns:
        The enclosing composable instances' keys, dotted; empty at the root.
    """
    return _building.get()


class DeferredNode(Node, ABC):
    """Python-only declaration; never valid IR or a native registry entry."""

    __slots__ = ()
    memoized: ClassVar[bool] = True
    """False for a declaration whose output depends on more than its inputs.

    Every declaration enclosing one then depends on more than its inputs too, so
    none of them is reused either: each is built again on every pass.
    """

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

    def tracked(self) -> Mapping[str, object]:
        """Return the arguments whose field reads are recorded, by name.

        Returns:
            The arguments keyed by type rather than identity; none by default.
        """
        return {}

    def inputs(self) -> Iterator[object]:
        """Yield every value this declaration was given, nested ones included.

        Yields:
            object: Each argument value; none by default.
        """
        yield from ()


@dataclass(slots=True)
class _Frame:
    node: Node
    prefix: str
    output: list[Node]
    children: list[Node] = field(default_factory=list)
    reads: Reads | None = ()
    parent: _Frame | None = None
    volatile: bool = False
    """Whether an unmemoized declaration was expanded in this frame's subtree."""


def _passes_on(built: tuple[Node, ...], ids: Collection[int]) -> bool:
    """Report whether a declaration in ``built`` was given one of ``ids``.

    Args:
        built: Nodes a build produced, walked down to the declarations in them.
        ids: Identities of the build's tracked arguments.

    Returns:
        True when one of them was passed on.
    """
    pending = list(built)
    while pending:
        node = pending.pop()
        if isinstance(node, DeferredNode):
            if any(id(value) in ids for value in node.inputs()):
                return True
            continue
        pending.extend(node.children)
    return False


class _Entry(NamedTuple):
    node: Node
    produced: tuple[Node, ...]
    reads: Reads | None


def _field(owner: object, name: str) -> object:
    """Read a field without recording the read."""
    return object.__getattribute__(owner, name)


def _holds(entry: _Entry, node: Node) -> bool:
    """Report whether everything an entry's build read is unchanged for ``node``.

    Args:
        entry: The memo entry from the last pass.
        node: The declaration being expanded now, under the same key.

    Returns:
        True when the entry's output is still this declaration's output.
    """
    now = node.tracked() if isinstance(node, DeferredNode) else {}
    if entry.reads is None:
        # Something read was not a tracked argument: only the same objects hold.
        before = entry.node.tracked() if isinstance(entry.node, DeferredNode) else {}
        return all(now.get(name) is value for name, value in before.items())
    return all(
        name in now and _field(now[name], attribute) == value
        for name, attribute, value in entry.reads
    )


def _reads_of(
    node: DeferredNode, reads: list[tuple[object, str]], built: tuple[Node, ...]
) -> Reads | None:
    """Name each recorded read by the tracked argument it was made on.

    A build that hands a tracked argument on to a declaration it produced has,
    in effect, read all of it: reusing that output would give the child the
    old object. Such a build, like one reading anything else, holds only for
    the same objects.

    Args:
        node: The declaration that was built.
        reads: The reads its build made.
        built: What the build produced.

    Returns:
        The reads by argument, or None when the build holds only for the same
        objects.
    """
    names = {id(value): name for name, value in node.tracked().items()}
    if names and _passes_on(built, names.keys()):
        return None
    named: dict[tuple[str, str], object] = {}
    for owner, attribute in reads:
        name = names.get(id(owner))
        if name is None:
            return None
        named[(name, attribute)] = _field(owner, attribute)
    return tuple((name, attribute, value) for (name, attribute), value in named.items())


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
        self._previous: dict[object, _Entry] = {}
        self._current: dict[object, _Entry] = {}
        self._reuses = 0
        self.reasons: list[str] = []

    def _start(self) -> None:
        self._previous, self._current = self._current, {}
        self.reasons = []

    def _lookup(self, key: object, node: Node) -> tuple[Node, ...] | None:
        entry = self._previous.get(key)
        if entry is None:
            return None
        if not _holds(entry, node):
            self.reasons.append(_reason(entry, node))
            return None
        self._current[key] = entry
        self._reuses += 1
        verify = self.verify_every and self._reuses % self.verify_every == 0
        return None if verify else entry.produced

    def _store(
        self, key: object, node: Node, produced: tuple[Node, ...], reads: Reads | None
    ) -> None:
        cached = self._previous.get(key)
        if cached is not None and _holds(cached, node) and cached.produced != produced:
            raise IrValidationError(
                "composable output changed while its inputs did not; "
                "it reads something outside its arguments",
                node_id=node.id,
                source=node.source if isinstance(node, DeferredNode) else None,
            )
        # The entry holds the declaration, so its identity-keyed inputs stay
        # alive and their ids cannot be reused by unrelated objects.
        self._current[key] = _Entry(node, produced, reads)


def _reason(entry: _Entry, node: Node) -> str:
    """Say why a composable re-ran, for the debug rebuild report.

    Args:
        entry: Its entry from the last pass.
        node: Its declaration now.

    Returns:
        The composable and the first field whose change made it re-run.
    """
    source = node.source if isinstance(node, DeferredNode) else node.id
    now = node.tracked() if isinstance(node, DeferredNode) else {}
    for name, attribute, value in entry.reads or ():
        if name not in now or _field(now[name], attribute) != value:
            return f"{source}: {name}.{attribute} changed"
    return f"{source}: an argument it read outside its fields changed"


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
            token = _building.set(frame.prefix)
            try:
                with recording() as reads:
                    built = node.build()
            finally:
                _building.reset(token)
            frame.reads = _reads_of(node, reads, built)
            return built
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
        if isinstance(node, DeferredNode) and not node.memoized:
            frame.volatile = True
        if frame.volatile and frame.parent is not None:
            # An enclosing declaration's output holds this one's, so it too
            # depends on more than its inputs and must not be reused.
            frame.parent.volatile = True
        if isinstance(node, DeferredNode):
            self.definitions.remove(node.recursion_key)
            self.context.pop()
            produced = tuple(
                child if node.slot is None else child.with_slot(node.slot)
                for child in frame.children
            )
            frame.output.extend(produced)
            if memo is not None and not frame.volatile:
                memo._store(_memo_key(frame), node, produced, frame.reads)
            return
        identity = f"{frame.prefix}.{node.id}" if frame.prefix and node.id else node.id
        # A root a composable produced without an id is keyed by the instance
        # that produced it, so sibling instances never share a site.
        site = (
            f"{frame.prefix.replace('.', '/')}>{node.site}"
            if frame.prefix and not node.id
            else node.site
        )
        unchanged = identity == node.id and site == node.site
        unchanged = unchanged and len(frame.children) == len(node.children)
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
                site=site,
            )
        )
        frame.output.append(result)


def _memo_key(frame: _Frame) -> object:
    node = frame.node
    assert isinstance(node, DeferredNode)
    return (frame.prefix, node.id or node.site, node.slot, node.recursion_key)


def _require_keyed_instances(children: tuple[Node, ...]) -> None:
    """Refuse a composable declared repeatedly among its siblings without an id.

    Its instances would be told apart only by their order, so a reorder would
    hand one instance's identity, and its native state, to another.

    Args:
        children: One parent's children in order.

    Raises:
        IrValidationError: If a composable call site repeats without ids.
    """
    for child, (_, repeated) in zip(children, sibling_keys(children), strict=True):
        if repeated and isinstance(child, DeferredNode):
            raise IrValidationError(
                "a composable declared repeatedly among its siblings needs an id",
                source=child.source,
            )


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
        if (
            memo is not None
            and isinstance(frame.node, DeferredNode)
            and frame.node.memoized
        ):
            reused = memo._lookup(_memo_key(frame), frame.node)
            if reused is not None:
                frame.output.extend(reused)
                continue
        children = expansion.enter(frame)
        pending.append((frame, False))
        prefix = ""
        if isinstance(frame.node, DeferredNode):
            own = frame.node.id or frame.node.site
            prefix = f"{frame.prefix}.{own}" if frame.prefix else own
        _require_keyed_instances(children)
        pending.extend(
            (_Frame(child, prefix, frame.children, parent=frame), True)
            for child in reversed(children)
        )
    if len(output) != 1:
        raise IrValidationError("composition must produce one root")
    return output[0]
