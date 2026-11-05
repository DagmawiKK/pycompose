"""A value family that reads the theme: its resolver, pure given the scheme.

A colour may name a theme role, and ``MaterialTheme.colorScheme`` is a read of
composition. So a family whose branches name the theme gets a resolver taking
the ``ColorScheme`` instead, and its composable resolver passes the theme's:
a caller that captured the scheme once in composition reads anywhere, a draw
block too.
"""

from __future__ import annotations

THEME = "androidx.compose.material3.MaterialTheme.colorScheme"
"""The theme's colours, a composition read; a family naming them reads the scheme."""

SCHEME = "androidx.compose.material3.ColorScheme"


def themed(
    method: str,
    family: str,
    native: str,
    opt_in: list[str],
    parse: str,
    branches: list[str],
) -> list[str]:
    """The resolvers of a family that reads the theme.

    Args:
        method: The resolver's name.
        family: The value family.
        native: The Kotlin type it resolves to.
        opt_in: Any opt-in annotation lines its members need.
        parse: The line reading the family's wire value into ``parsed``.
        branches: Its ``when`` branches, naming the theme.

    Returns:
        The composable resolver, then the pure ones taking the scheme.
    """
    return [
        "    @Composable",
        *opt_in,
        f"    fun {method}(value: {family}Value): {native} =",
        f"        {method}(value, {THEME})",
        "",
        *opt_in,
        f"    fun {method}(value: JsonElement, scheme: {SCHEME}): Result<{native}> {{",
        parse,
        f"        return Result.success({method}(parsed, scheme))",
        "    }",
        "",
        *opt_in,
        f"    fun {method}(value: {family}Value, scheme: {SCHEME}): {native} =",
        "        when (value) {",
        *(line.replace(THEME, "scheme") for line in branches),
        "        }",
        "",
    ]
