"""How a generated adapter spells the wire in Kotlin.

The tables are the embedding policy every adapter follows: which Kotlin type a
wire type becomes, which resolver decodes a prop family, what it returns and
falls back to, and the package of every bare Compose name the generator writes.
"""

from __future__ import annotations

SCALAR_KOTLIN = {
    "string": "String",
    "boolean": "Boolean",
    "integer": "Long",
    "number": "Double",
}


DECODED = {"enum", "color", "resource"}
"""Prop types that arrive on the wire as something other than their Kotlin type."""


RESOLVER_RETURN = {
    "alignment": "Alignment",
    "arrangement": "Arrangement.Vertical",
    "color": "Color",
    "horizontal": "Alignment.Horizontal",
    "resourceFont": "FontFamily?",
    "resourceImage": "Painter?",
    "resourceText": "String?",
    "textStyle": "TextStyle",
    "tooltipPosition": "TooltipAnchorPosition",
    "vertical": "Alignment.Vertical",
}
"""What each decoder hands back.

Needed because a prop's Kotlin type is not its wire type: the wire carries the
string ``"start"`` and Compose wants an ``Alignment.Horizontal``. The schema's
``decode`` names the resolver; this says what comes out of it, so a generated
adapter can declare the local it assigns to.
"""


RESOLVER_FALLBACK = {
    "alignment": "Alignment.TopStart",
    "arrangement": "Arrangement.Top",
    "color": "Color.Unspecified",
    "horizontal": "Alignment.Start",
    "resourceFont": "null",
    "resourceImage": "null",
    "resourceText": "null",
    "textStyle": "MaterialTheme.typography.bodyMedium",
    "tooltipPosition": "TooltipAnchorPosition.Above",
    "vertical": "Alignment.Top",
}
"""What a malformed value falls back to.

Degrade, never throw: Compose must not see an exception from a bad prop in a
debug snapshot (ADR-0005). Each is the value the hand-written adapter already
chose for the same prop, so generating does not change behaviour.
"""


KOTLIN_TYPES = {
    "Alignment": "androidx.compose.ui.Alignment",
    "Arrangement": "androidx.compose.foundation.layout.Arrangement",
    "Color": "androidx.compose.ui.graphics.Color",
    "FontFamily": "androidx.compose.ui.text.font.FontFamily",
    "MaterialTheme": "androidx.compose.material3.MaterialTheme",
    "Painter": "androidx.compose.ui.graphics.painter.Painter",
    "PropResolver": "com.pycompose.renderer.PropResolver",
    "TextStyle": "androidx.compose.ui.text.TextStyle",
    "TooltipAnchorPosition": "androidx.compose.material3.TooltipAnchorPosition",
    "TooltipPropResolver": "com.pycompose.renderer.TooltipPropResolver",
}
"""Package for every bare Compose name this generator emits.

Generated code names resolvers and their returns in full instead of importing
them, the way the value path already did: one less import list to keep honest,
and a name that cannot be shadowed by a prop.
"""


RESOLVER_OWNER = {"tooltipPosition": "TooltipPropResolver"}
"""Specialised native decoders; other non-resource decoders use PropResolver."""


MECHANICAL = {"string", "boolean", "integer", "number", "actionId", "modifier"}
"""Schema prop types an adapter can render with no decision and no decoder.

``color``, ``enum`` and ``resource`` are renderable too, but only when the prop
declares a ``decode``: those types arrive on the wire as strings and need a
resolver to become a ``Color`` or an ``Alignment``. A prop of one of those types
with no ``decode`` is refused, because guessing which family its values belong to
is how an adapter silently renders the wrong alignment.
"""


NUMERIC_KOTLIN = frozenset({"Byte", "Short", "Int", "Long", "Float", "Double"})
"""Kotlin's numeric primitives: the only types a provider coerces between."""


NUMERIC_CONVERSIONS = {
    ("Double", "Float"): "toFloat",
    ("Double", "Int"): "toInt",
    ("Double", "Long"): "toLong",
    ("Float", "Double"): "toDouble",
    ("Int", "Float"): "toFloat",
    ("Int", "Long"): "toLong",
    ("Long", "Double"): "toDouble",
    ("Long", "Float"): "toFloat",
    ("Long", "Int"): "toInt",
}
"""Each entry is Kotlin's own named conversion; an unlisted pair is refused."""


def qualify(source: str) -> str:
    """Fully qualify a Kotlin expression's leading type name.

    Args:
        source: Kotlin source, e.g. ``Arrangement.Vertical`` or ``Color?``.

    Returns:
        The source with a known leading type name replaced by its package-qualified
        spelling; anything already qualified or unknown is returned unchanged.
    """
    head, separator, rest = source.partition(".")
    nullable = head.endswith("?")
    bare = head[:-1] if nullable else head
    qualified = KOTLIN_TYPES.get(bare)
    if qualified is None:
        return source
    return f"{qualified}{'?' if nullable else ''}{separator}{rest}"


def camel(name: str) -> str:
    """Return a snake_case wire name as camelCase.

    Args:
        name: The schema's prop name.

    Returns:
        The Kotlin property name.
    """
    head, *rest = name.split("_")
    return head + "".join(pascal(word) for word in rest)


def pascal(name: str) -> str:
    """Return a name with its first letter capitalised, the rest as written."""
    return name[:1].upper() + name[1:]


def simple(scope: str) -> str:
    """A scope's class as the adapters spell it: imported, so by simple name."""
    return scope.rsplit(".", 1)[-1]
