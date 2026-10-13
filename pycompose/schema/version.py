"""Pure numeric compatibility checks for the three-way version contract."""

from __future__ import annotations

import re

from pycompose.errors import SchemaError

__all__ = ["require_version"]

_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def _parts(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or _VERSION.fullmatch(value) is None:
        raise SchemaError("version must be MAJOR.MINOR.PATCH", version=value)
    return tuple(int(part) for part in value.split("."))


def require_version(
    version: str,
    *,
    minimum: str,
    maximum: str | None = None,
    field: str = "schemaVersion",
    supported: tuple[str, ...] | None = None,
) -> None:
    """Reject malformed or unsupported versions using numeric comparison.

    Args:
        version: Candidate version.
        minimum: Inclusive minimum compatible version.
        maximum: Inclusive maximum, if only a bounded contract is supported.
        field: Wire field named in errors.
        supported: Explicit versions, when numeric ranges are insufficient.

    Raises:
        SchemaError: If a version is malformed or outside the supported range.
    """
    candidate = _parts(version)
    if supported is not None and version not in supported:
        raise SchemaError("unsupported schema version", field=field, version=version)
    if candidate < _parts(minimum):
        raise SchemaError(
            "version below supported minimum",
            field=field,
            version=version,
            minimum=minimum,
        )
    if maximum is not None and candidate > _parts(maximum):
        raise SchemaError(
            "version above supported maximum",
            field=field,
            version=version,
            maximum=maximum,
        )
