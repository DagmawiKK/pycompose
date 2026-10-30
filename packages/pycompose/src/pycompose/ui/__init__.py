"""pycompose.ui — everything a screen is described with.

Every component the catalog declares, ``Modifier``, the value types (``Color``,
``Dp``, ``TextStyle``…), ``Fallback`` and ``Intent``: the one import an app
needs to draw.

Components load on first use. An app on its own slice (ADR-0014) imports them
from its ``components`` package instead, and its APK ships without the
library's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pycompose.ui._generated.values import *  # noqa: F403 -- the catalog's values

# The redundant aliases re-export: the star imports leave no room for __all__.
from pycompose.ui.fallback import Fallback as Fallback  # noqa: PLC0414
from pycompose.ui.intents import Intent as Intent  # noqa: PLC0414
from pycompose.ui.modifier import Modifier as Modifier  # noqa: PLC0414

if TYPE_CHECKING:
    from pycompose.ui._generated.components import *  # noqa: F403


def __getattr__(name: str) -> Any:
    from pycompose.ui._generated import components

    if name in components.__all__:
        return getattr(components, name)
    raise AttributeError(f"module 'pycompose.ui' has no attribute {name!r}")
