"""Keyed content: a generic composable that draws one subtree per value.

``AnimatedContent(targetState: S, content: AnimatedContentScope.(S) -> Unit)``
animates between values of a type the caller picks. Python cannot hand Kotlin
a lambda, but it can name the value: ``S`` crosses the wire as a string key,
and the children are the subtree Python sends for the current key. The host
keeps each outgoing key's subtree while its transition plays (``keyedContent``).
"""

from __future__ import annotations

from pycompose_codegen.derive.classpath_dump import Declaration
from pycompose_codegen.derive.classpath_types import KotlinType

KEY = "#0"
"""The pin's spelling of a declaration's first (and here only) type parameter."""

COMPOSABLE = "androidx/compose/runtime/Composable"


def keyed_arguments(value: KotlinType) -> bool:
    """Whether a composable lambda's arguments, past any receiver, are just the key.

    Args:
        value: The lambda's type.

    Returns:
        True for ``(S) -> Unit`` and ``Scope.(S) -> Unit``.
    """
    arguments = [type_ for _, type_ in value.arguments]
    if "kotlin/ExtensionFunctionType" in value.annotations:
        arguments = arguments[1:]
    return [a.classifier if a else None for a in arguments] == [KEY, "kotlin/Unit"]


def is_keyed(source: Declaration) -> bool:
    """Whether a generic declaration is keyed content, and so needs no protocol.

    One type parameter; one required, non-null value parameter of that type;
    one required composable lambda taking it. Anything else naming the type
    parameter (``contentKey``) has a default and is left to Compose.

    Args:
        source: The pinned declaration.

    Returns:
        Whether the planner may bind it.
    """
    if len(source.document.get("typeParameters") or []) != 1:
        return False
    keys = [p for p in source.parameters if p.type.classifier == KEY]
    contents = [
        p
        for p in source.parameters
        if COMPOSABLE in p.type.annotations and keyed_arguments(p.type)
    ]
    others = [
        p
        for p in source.parameters
        if p not in keys + contents and KEY in str(p.type.document)
    ]
    return (
        len(keys) == 1
        and keys[0].required
        and not keys[0].type.nullable
        and len(contents) == 1
        and contents[0].required
        and all(p.has_default for p in others)
    )
