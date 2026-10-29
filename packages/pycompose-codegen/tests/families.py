"""Value families the codegen tests share."""

from __future__ import annotations

RANGE_FAMILY = {
    "family": "Range",
    "kind": "operator",
    "kotlinType": "kotlin.ranges.ClosedFloatingPointRange",
    "since": "1.23.0",
    "source": {
        "language": "kotlin",
        "operator": "..",
        "evidence": "kotlin/ranges/Ranges.kt",
    },
    "parameters": {
        "start": {"type": "float", "required": True},
        "end": {"type": "float", "required": True},
    },
    "native": {"operator": ".."},
}
