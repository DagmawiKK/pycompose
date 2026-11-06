"""Generate each native holder's drive function from the catalog's holders."""

from typing import Any

from pycompose_codegen.emit.literals import GENERATED_NOTICE


def render_holder_drives(registry: dict[str, Any]) -> str:
    """Render one ``driveTo`` per holder, an exhaustive ``when`` over its value enum.

    The table is pinned evidence (``tools/schema/holders.py``), so the renderer
    never hand-maps an anchor to a member, and the compiler proves every anchor
    of the enum has a drive.

    Args:
        registry: The validated catalog mapping.

    Returns:
        The Kotlin source of ``HolderDrives.kt``.
    """
    holders = registry.get("holders", {})
    markers = sorted({m for spec in holders.values() for m in spec["optIn"]})
    lines = [f"// {GENERATED_NOTICE}"]
    if markers:
        lines += ["@file:OptIn(" + ", ".join(f"{m}::class" for m in markers) + ")", ""]
    lines += ["package com.pycompose.renderer.generated", ""]
    for holder, spec in sorted(holders.items()):
        value = spec["value"]
        lines += [
            f"/** Drive [{holder}] to [anchor] through its pinned member. */",
            f"suspend fun {holder}.driveTo(anchor: {value}) {{",
            "    when (anchor) {",
            *(
                f"        {value}.{entry} -> "
                f"{drive['method']}({'anchor' if drive.get('anchor') else ''})"
                for entry, drive in spec["drives"].items()
            ),
            "    }",
            "}",
            "",
        ]
    return "\n".join(lines)
