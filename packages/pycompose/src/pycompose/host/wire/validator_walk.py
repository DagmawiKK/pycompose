"""Depth-first snapshot walk for IR validation.

Each node is checked by the rules a constructor runs (:mod:`pycompose.ui._rules`);
the walk adds what only a whole snapshot has: unique ids across it, the root's
place, and the subtrees that were clean last pass. It raises with node context
at the first invalid node: Python validates in debug and tests, where an
invalid snapshot is a bug to report, never a tree to repair. Release leaves
validation to the host's typed parse.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pycompose.model.nodes.node import Node
from pycompose.model.nodes.traversal import walk_nodes
from pycompose.ui._rules import _NodeFrame, _Validation


def walk(validation: _Validation, root: Node) -> None:
    """Check every node under ``root``, raising at the first invalid one.

    Args:
        validation: The snapshot's rules, ids and memo.
        root: The snapshot's root.
    """
    if root.slot is not None:
        # The root has no parent to fill a slot of.
        validation.report("the root cannot fill a slot", root)
    visit = _Walk(validation)
    for node, entering in walk_nodes(root, visit.prune):
        if entering:
            visit.enter(node)
        else:
            visit.exit(node)


@dataclass(slots=True)
class _Visit:
    frame: _NodeFrame | None
    reused: tuple[str, ...] | None
    ids: list[str] = field(default_factory=list)


class _Walk:
    """One validation walk; a subtree that was clean last pass is not re-checked.

    Validity of a subtree depends only on itself and the schema version, given
    the parent accepts it, which is still checked here. Its ids are claimed
    again, so a duplicate across subtrees is still found.
    """

    def __init__(self, validation: _Validation) -> None:
        self.validation = validation
        self.visits: list[_Visit] = []
        self.candidate: tuple[str, ...] | None = None

    def prune(self, node: Node) -> bool:
        memo = self.validation.memo
        self.candidate = (
            memo.get(node, self.validation.schema_version) if memo is not None else None
        )
        return self.candidate is not None

    def enter(self, node: Node) -> None:
        validation = self.validation
        validation.path.append(node.id)
        reused, self.candidate = self.candidate, None
        visit = _Visit(None, reused)
        if reused is None:
            visit.frame = validation.prepare(node)
            visit.ids.append(node.id)
        elif validation.ids.isdisjoint(reused):
            validation.ids.update(reused)
            visit.ids.extend(reused)
        else:
            validation.report("duplicate node id", node)
        self.visits.append(visit)

    def exit(self, node: Node) -> None:
        validation = self.validation
        visit = self.visits.pop()
        if visit.frame is not None:
            validation.finish(node, visit.frame)
            # Reaching here means the whole subtree was valid.
            if validation.memo is not None:
                validation.memo.put(node, tuple(visit.ids), validation.schema_version)
        validation.path.pop()
        if self.visits:
            parent = self.visits[-1]
            parent.ids.extend(visit.ids)
            if parent.frame is not None and node.slot is None:
                parent.frame.unslotted += 1
