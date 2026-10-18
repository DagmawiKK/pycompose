"""Named requirement validation; target resolution belongs to Chaquopy, not pip."""

from __future__ import annotations

from packaging.requirements import InvalidRequirement, Requirement

from pycompose.cli.project import ProjectError


def validate_requirements(values: object, *, field: str) -> list[str]:
    """Validate packaging syntax without evaluating desktop environment markers.

    Args:
        values: An array of named requirement strings.
        field: Configuration location for actionable diagnostics.

    Returns:
        Stripped declarations, preserving their constraints, extras and markers.

    Raises:
        ProjectError: If a declaration is malformed or uses an unsupported source.
    """
    if not isinstance(values, list):
        raise ProjectError(f"{field} must be an array of package specifiers")
    result = []
    for index, value in enumerate(values):
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ProjectError(
                f"{field} entries must be nonempty single-line strings", index=index
            )
        text = value.strip()
        try:
            requirement = Requirement(text)
        except InvalidRequirement as exc:
            raise ProjectError(
                f"{field} entries must be named pip package specifiers", index=index
            ) from exc
        if requirement.url is not None or text.casefold().endswith(
            (".whl", ".tar.gz", ".zip")
        ):
            raise ProjectError(f"{field} accepts named packages only", index=index)
        result.append(text)
    return result
