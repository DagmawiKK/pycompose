"""Apply the generated IR schema vocabulary without on-device dependencies.

This is not a general JSON Schema engine: disjunctions in the generated IR
contract are type-discriminated registrations. Unknown schema keywords fail
closed so generator changes cannot silently weaken CLI validation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from importlib.resources import files
from typing import Any, cast

from pycompose.cli.project import ProjectError

TYPE_CHECKS: dict[str, Callable[[object], bool]] = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "boolean": lambda value: isinstance(value, bool),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, int | float)
    and not isinstance(value, bool),
}
KEYWORDS = frozenset(
    {
        "$id",
        "$schema",
        "title",
        "definitions",
        "type",
        "properties",
        "const",
        "default",
        "enum",
        "required",
        "additionalProperties",
        "minLength",
        "minItems",
        "minimum",
        "maximum",
        "items",
        "$ref",
        "allOf",
        "anyOf",
        "if",
        "then",
        "pattern",
    }
)


def _scalars(item: object, rule: dict[str, Any], path: str) -> None:
    kind = rule.get("type")
    if kind is not None and (kind not in TYPE_CHECKS or not TYPE_CHECKS[kind](item)):
        raise ProjectError("wrong JSON type", path=path, expected=kind)
    if (
        "const" in rule
        and item != rule["const"]
        or "enum" in rule
        and item not in rule["enum"]
    ):
        raise ProjectError("value is not allowed by the IR schema", path=path)
    if isinstance(item, int | float):
        if "minimum" in rule and item < rule["minimum"]:
            raise ProjectError("value below minimum", path=path)
        if "maximum" in rule and item > rule["maximum"]:
            raise ProjectError("value above maximum", path=path)
    if (
        isinstance(item, str)
        and len(item) < rule.get("minLength", 0)
        or isinstance(item, list)
        and len(item) < rule.get("minItems", 0)
    ):
        raise ProjectError("value is too short", path=path)
    if (
        isinstance(item, str)
        and "pattern" in rule
        and re.search(rule["pattern"], item) is None
    ):
        raise ProjectError("invalid resource reference", path=path)


class WireSchema:
    """A compiled view of the bundled, generated IR schema."""

    def __init__(self) -> None:
        self._root: dict[str, Any] = json.loads(
            files("pycompose")
            .joinpath("schema", "ir.schema.json")
            .read_text(encoding="utf-8")
        )
        self._choices: dict[int, dict[str, dict[str, Any]]] = {}

    def _resolve(self, rule: dict[str, Any] | bool) -> dict[str, Any] | bool:
        if isinstance(rule, dict) and "$ref" in rule:
            return cast(
                "dict[str, Any] | bool",
                self._root["definitions"][rule["$ref"].removeprefix("#/definitions/")],
            )
        return rule

    def _choice(self, rule: dict[str, Any], value: object, path: str) -> dict[str, Any]:
        key = id(rule)
        if key not in self._choices:
            choices = {}
            for candidate in rule["anyOf"]:
                resolved = self._resolve(candidate)
                if isinstance(resolved, dict):
                    choices[resolved["properties"]["type"]["const"]] = resolved
            self._choices[key] = choices
        kind = value.get("type") if isinstance(value, dict) else None
        if not isinstance(kind, str) or kind not in self._choices[key]:
            raise ProjectError(
                "unknown or missing registered type", path=path, node_type=kind
            )
        return self._choices[key][kind]

    def check(self, value: object) -> None:
        """Validate raw JSON before it can be normalized into Python Nodes.

        Args:
            value: Parsed JSON snapshot.

        Raises:
            ProjectError: If a wire shape or generated schema rule is invalid.
        """
        pending: list[tuple[object, dict[str, Any] | bool, str]] = [
            (value, self._root, "$")
        ]
        while pending:
            item, source, path = pending.pop()
            rule = self._resolve(source)
            if rule is False:
                raise ProjectError("field is forbidden by the IR schema", path=path)
            if rule is True:
                continue
            if set(rule) - KEYWORDS:
                raise ProjectError("unsupported generated schema keyword", path=path)
            _scalars(item, rule, path)
            if "if" in rule:
                selected = self._version_branch(rule, item, path)
                if selected is not None:
                    pending.append((item, selected, path))
            pending.extend((item, child, path) for child in rule.get("allOf", []))
            if "anyOf" in rule:
                pending.append((item, self._choice(rule, item, path), path))
            if isinstance(item, dict):
                missing = set(rule.get("required", [])) - item.keys()
                if missing:
                    raise ProjectError(
                        "missing required fields", path=path, fields=sorted(missing)
                    )
                props = rule.get("properties", {})
                extra = item.keys() - props.keys()
                if extra and rule.get("additionalProperties") is False:
                    raise ProjectError(
                        "unknown fields", path=path, fields=sorted(extra)
                    )
                pending.extend(
                    (child, props[name], f"{path}.{name}")
                    for name, child in item.items()
                    if name in props
                )
            if isinstance(item, list) and "items" in rule:
                pending.extend(
                    (child, rule["items"], f"{path}[{index}]")
                    for index, child in enumerate(item)
                )

    def _version_branch(
        self, rule: dict[str, Any], item: object, path: str
    ) -> dict[str, Any] | None:
        # Only schema-version selectors are supported, not arbitrary predicates.
        condition = rule["if"]
        if set(condition) != {"properties"} or set(condition["properties"]) != {
            "schemaVersion"
        }:
            raise ProjectError("unsupported schema condition", path=path)
        selector = condition["properties"]["schemaVersion"]
        if set(selector) != {"const"} or "then" not in rule:
            raise ProjectError("unsupported schema condition", path=path)
        if isinstance(item, dict) and item.get("schemaVersion") == selector["const"]:
            return cast("dict[str, Any]", rule["then"])
        return None
