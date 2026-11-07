"""Share identical definitions in the IR schema instead of repeating them.

Every supported envelope selects its own recursive catalog, so a component
that did not change between versions is written once per version, and the
open minor's catalog repeats the current one whole. Definitions are compared
by content, a definition's references to itself read as one placeholder, and
each duplicate is folded into the first of its kind: an unversioned definition
before a versioned one, an older version before a newer. References follow the
fold until nothing more is equal, so a node schema whose component references
became equal folds too. The schema accepts exactly what it did.
"""

from __future__ import annotations

import json
from typing import Any

PREFIX = "#/definitions/"
SELF = "#/self"


def share_definitions(schema: dict[str, Any]) -> dict[str, Any]:
    """Fold every duplicate definition into its first equal, rewriting references.

    Args:
        schema: The IR schema, whose ``definitions`` may repeat themselves.

    Returns:
        The same schema with each definition written once.
    """
    definitions: dict[str, Any] = schema["definitions"]
    while True:
        first: dict[str, str] = {}
        folds: dict[str, str] = {}
        for name in sorted(definitions, key=_order):
            text = json.dumps(
                _retarget(definitions[name], {name: SELF}), sort_keys=True
            )
            if text in first:
                folds[name] = first[text]
            else:
                first[text] = name
        if not folds:
            return schema
        for name in folds:
            del definitions[name]
        schema = _retarget(schema, folds)
        definitions = schema["definitions"]


def _order(name: str) -> tuple[bool, tuple[int, ...], str]:
    """Unversioned names first, then versions oldest first: who a fold keeps."""
    if not name.startswith("V_"):
        return (False, (), name)
    major, minor, patch, rest = name[2:].split("_", 3)
    return (True, (int(major), int(minor), int(patch)), rest)


def _retarget(value: Any, folds: dict[str, str]) -> Any:
    """A copy of ``value``, each reference to a folded name pointing to its keeper."""
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.removeprefix(PREFIX) in folds:
            target = folds[ref.removeprefix(PREFIX)]
            value = {**value, "$ref": target if target == SELF else PREFIX + target}
        return {key: _retarget(item, folds) for key, item in value.items()}
    if isinstance(value, list):
        return [_retarget(item, folds) for item in value]
    return value
