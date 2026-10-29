"""Moved to :mod:`pycompose.ui`; this name works for one release."""

from pycompose._moved import forward

forward(
    __name__,
    "pycompose.ui",
    globals(),
    submodules={
        "base": "pycompose.ui.base",
        "buttons": "pycompose.ui.buttons",
        "fallback": "pycompose.ui.fallback",
        "input": "pycompose.ui.input",
        "layout": "pycompose.ui.layout",
        "lists": "pycompose.ui.lists",
        "modifier_operation": "pycompose.ui.modifier_operation",
        "modifiers": "pycompose.ui.modifiers",
        "primitives": "pycompose.ui.primitives",
        "scoped_modifiers": "pycompose.ui.scoped_modifiers",
        "windowed": "pycompose.ui.windowed",
    },
)
