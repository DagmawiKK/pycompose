"""Pure-data resource reference grammar shared by all resource props."""

import re

_NATIVE = re.compile(r"[a-z][a-z0-9_]*")
_ASSET_SEGMENT = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*")


def valid_resource(value: object, kinds: tuple[str, ...]) -> bool:
    """Check a resource name without touching the platform or filesystem.

    Args:
        value: Candidate @kind/name reference.
        kinds: Resource kinds allowed by the manifest prop.

    Returns:
        Whether the name is valid and traversal-free for an allowed kind.
    """
    if not isinstance(value, str) or not value.startswith("@") or "/" not in value:
        return False
    kind, name = value[1:].split("/", 1)
    if kind not in kinds:
        return False
    if kind == "asset":
        return all(_ASSET_SEGMENT.fullmatch(part) for part in name.split("/"))
    return _NATIVE.fullmatch(name) is not None
