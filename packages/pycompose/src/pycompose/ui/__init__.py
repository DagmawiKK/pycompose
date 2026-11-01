"""pycompose.ui — everything a screen is described with.

Every component the catalog declares, ``Modifier``, the value types (``Color``,
``Dp``, ``TextStyle``…), ``Fallback``, ``Intent`` and ``Node``, the type a
screen returns: the one import an app needs to draw.

Components load on first use. An app on its own slice (ADR-0014) imports them
from its ``components`` package instead, and its APK ships without the
library's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# The redundant aliases re-export: the star imports leave no room for __all__.
from pycompose.model.nodes.node import Node as Node  # noqa: PLC0414
from pycompose.ui._generated.values import *  # noqa: F403 -- the catalog's values
from pycompose.ui.fallback import Fallback as Fallback  # noqa: PLC0414
from pycompose.ui.host import Binding as Binding  # noqa: PLC0414
from pycompose.ui.host import HostFunction as HostFunction  # noqa: PLC0414
from pycompose.ui.host import animate as animate  # noqa: PLC0414
from pycompose.ui.host import follow as follow  # noqa: PLC0414
from pycompose.ui.host import host as host  # noqa: PLC0414
from pycompose.ui.host import spring as spring  # noqa: PLC0414
from pycompose.ui.host import tween as tween  # noqa: PLC0414
from pycompose.ui.intents import Intent as Intent  # noqa: PLC0414
from pycompose.ui.modifier import Modifier as Modifier  # noqa: PLC0414

if TYPE_CHECKING:
    from pycompose.ui._generated.components import *  # noqa: F403


def __getattr__(name: str) -> Any:
    from pycompose.ui._generated import components

    if name in components.__all__:
        return getattr(components, name)
    raise AttributeError(f"module 'pycompose.ui' has no attribute {name!r}")
