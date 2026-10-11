"""Material 3 input components."""

from pycompose.components.base import Component


class TextField(Component):
    """Field with value, registered on_value_change action id and optional label."""

    __slots__ = ()
    component_type = "TextField"
