"""Measure IR updates; timing and traced memory run in separate processes.

Run with Python 3.12 from the repo root:
    python tools/bench_ir.py --rigorous -o timing.json
    python tools/bench_ir.py --memory-report memory.json
    python tools/bench_ir.py --phases construction,emit,validate,bytes -o phases.json

The ``diff``, ``patch``, and ``patch_pipeline`` phases measure ADR-0018's patch
path (one keystroke against the same shapes) next to the full-snapshot path.
``reuse_pipeline`` publishes that keystroke and its undo in turn under one
session's ``Reuse``, so unchanged subtrees are not emitted, validated or
serialized again -- the steady state of an app being typed into.

Compare matched machines with ``python -m pyperf compare_to before.json after.json``.
tracemalloc reports peak/retained bytes, not total allocation churn. Results remain
informational until runner variability establishes defensible regression thresholds.
Prepared input is outside the traced interval; total includes construction. Block
counts are retained allocations with the operation's output alive, not churn.
"""

from __future__ import annotations

import argparse
import gc
import json
import platform
import sys
import tracemalloc
from collections.abc import Callable
from pathlib import Path

import pyperf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pycompose.model.nodes import Node, Props

# CI runs this same script against the base commit too: one from before
# session reuse has no ``reuse_pipeline`` to measure, and skips that phase.
try:
    from pycompose.model.nodes.reuse import Reuse
except ImportError:
    Reuse = None  # type: ignore[assignment,misc]
try:
    from pycompose.wire import emit_ir, to_json_bytes, validate_ir
    from pycompose.wire.model import IRRoot
    from pycompose.wire.patch import diff_nodes, patch_bytes
except ImportError:  # a base commit from before the package was named wire
    from pycompose.ir import (  # type: ignore[no-redef]
        emit_ir,
        to_json_bytes,
        validate_ir,
    )
    from pycompose.ir.model import IRRoot  # type: ignore[no-redef]
    from pycompose.ir.patch import diff_nodes, patch_bytes  # type: ignore[no-redef]
from pycompose.state import State

SHAPES = ("wide", "nested", "props", "drop", "optional")
SIZES = (100, 1000)


def build_state(size: int, shape: str) -> State:
    leaves = []
    wrappers = (size - 1) // 10 if shape == "nested" else 0
    for index in range(size - 1 - wrappers):
        props = {"text": f"Item {index}: café 👋"}
        if shape == "props":
            props["modifier"] = {
                "padding": {"start": 1.25, "end": 8, "edges": [0, 4, 8, 16]},
                "tags": [{"name": f"tag-{tag}", "enabled": True} for tag in range(8)],
            }
        if shape == "optional" and index == 0:
            props["style"] = "invalid"
        leaves.append(
            Node(
                id=f"item{index}",
                type="Unknown" if shape == "drop" and index == 0 else "Text",
                props=Props(props),
            )
        )
    if wrappers:
        groups = [
            Node(
                id=f"group{index}",
                type="Column",
                children=tuple(leaves[index::wrappers]),
            )
            for index in range(wrappers)
        ]
        leaves = groups
    if shape == "drop":
        descendants = max(10, size // 10)
        unknown = Node(
            id="item0", type="Unknown", children=tuple(leaves[1 : descendants + 1])
        )
        leaves = [unknown, *leaves[descendants + 1 :]]
    return State(root=Node(id="root", type="Column", children=tuple(leaves)))


def pipeline(state: State) -> bytes:
    result = validate_ir(emit_ir(state, "1.0.0"), debug=False)
    assert result.snapshot is not None
    return to_json_bytes(result.snapshot)


def patch_pipeline(state: State, base: IRRoot) -> bytes:
    result = validate_ir(emit_ir(state, "1.0.0"), debug=False)
    assert result.snapshot is not None
    ops = diff_nodes(base.root, result.snapshot.root)
    return patch_bytes(result.snapshot, ops, base_serial=1, serial=2, surface="main")


def reuse_pipeline(states: tuple[State, State], reuse: Reuse, turn: list[int]) -> bytes:
    turn[0] ^= 1
    result = validate_ir(
        emit_ir(states[turn[0]], "1.0.0", reuse), debug=False, reuse=reuse
    )
    assert result.snapshot is not None
    return to_json_bytes(result.snapshot, reuse)


def _edit_text(node: Node) -> tuple[Node, bool]:
    """Rewrite the last node carrying ``text`` with one more character.

    Args:
        node: Subtree to rewrite.

    Returns:
        The possibly rebuilt node and whether the edit happened below it.
    """
    if "text" in node.props:
        props = dict(node.props.values)
        props["text"] = f"{props['text']}!"
        return (
            Node(
                id=node.id,
                type=node.type,
                props=Props(props),
                children=node.children,
                slot=node.slot,
            ),
            True,
        )
    for index in range(len(node.children) - 1, -1, -1):
        edited, done = _edit_text(node.children[index])
        if done:
            children = (*node.children[:index], edited, *node.children[index + 1 :])
            return (
                Node(
                    id=node.id,
                    type=node.type,
                    props=node.props,
                    children=children,
                    slot=node.slot,
                ),
                True,
            )
    return node, False


def mutate(state: State) -> State:
    """Change one visible leaf's text; the keystroke the patch protocol targets.

    Args:
        state: State to copy with one edited leaf.

    Returns:
        The mutated state, structurally shared elsewhere.
    """
    root, edited = _edit_text(state.root)
    assert edited, "bench shapes always carry a text leaf"
    return State(root=root)


def operations(size: int, shape: str) -> dict[str, Callable[[], object]]:
    state = build_state(size, shape)
    candidate = emit_ir(state, "1.0.0")
    result = validate_ir(candidate, debug=False)
    assert result.snapshot is not None
    safe = result.snapshot
    edited_state = mutate(state)
    edited = validate_ir(emit_ir(edited_state, "1.0.0"), debug=False)
    assert edited.snapshot is not None
    ops = diff_nodes(safe.root, edited.snapshot.root)
    phases: dict[str, Callable[[], object]] = {
        "total": lambda: pipeline(build_state(size, shape)),
        "pipeline": lambda: pipeline(state),
        "construction": lambda: build_state(size, shape),
        "emit": lambda: emit_ir(state, "1.0.0"),
        "validate": lambda: validate_ir(candidate, debug=False),
        "bytes": lambda: to_json_bytes(safe),
        "diff": lambda: diff_nodes(safe.root, edited.snapshot.root),
        "patch": lambda: patch_bytes(
            edited.snapshot, ops, base_serial=1, serial=2, surface="main"
        ),
        "patch_pipeline": lambda: patch_pipeline(edited_state, safe),
    }
    if Reuse is not None:
        reuse, turn = Reuse(), [0]
        phases["reuse_pipeline"] = lambda: reuse_pipeline(
            (state, edited_state), reuse, turn
        )
    return phases


def memory_report(path: str) -> None:
    results = {}
    for size in SIZES:
        for shape in SHAPES:
            for phase, operation in operations(size, shape).items():
                operation()
                gc.collect()
                tracemalloc.start()
                output = operation()
                retained, peak = tracemalloc.get_traced_memory()
                blocks = sum(
                    stat.count
                    for stat in tracemalloc.take_snapshot().statistics("filename")
                )
                tracemalloc.stop()
                results[f"{shape}-{size}-{phase}"] = {
                    "retained_bytes": retained,
                    "peak_bytes": peak,
                    "retained_blocks": blocks,
                }
                del output
    Path(path).write_text(
        json.dumps(
            {
                "python": sys.version,
                "platform": platform.platform(),
                "results": results,
            },
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--memory-report")
    args, _ = parser.parse_known_args()
    if args.memory_report:
        memory_report(args.memory_report)
        return
    runner = pyperf.Runner(
        add_cmdline_args=lambda cmd, args: cmd.extend(["--phases", args.phases])
    )
    runner.argparser.add_argument("--phases", default="total,pipeline")
    args = runner.parse_args()
    runner.metadata["workload"] = "100/1000 nodes; wide,nested,props,drop,optional"
    for size in SIZES:
        for shape in SHAPES:
            for phase, operation in operations(size, shape).items():
                if phase in args.phases.split(","):
                    runner.bench_func(f"{shape}-{size}-{phase}", operation)


if __name__ == "__main__":
    main()
