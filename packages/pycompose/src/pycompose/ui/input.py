"""Material 3 input components."""

from pycompose.ui.base import Component


class TextField(Component):
    """Field with value, registered on_value_change action id and optional label."""

    __slots__ = ()
    component_type = "TextField"


class Checkbox(Component):
    """Binary control with a checked value and registered on_checked_change id."""

    __slots__ = ()
    component_type = "Checkbox"


class FilterChip(Component):
    """Selectable chip with a label, selected state and registered on_click id."""

    __slots__ = ()
    component_type = "FilterChip"
