"""The binding census: every approved value prop in one bucket, never none."""

from __future__ import annotations

from test_accounting import _registry


def test_binding_census_puts_every_value_prop_in_one_bucket() -> None:
    """Capability, authority, or the reason no converter exists: never nothing."""
    from pycompose_codegen.derive.accounting import binding_census

    registry = _registry(
        components={
            "Slider": {
                "props": {
                    "value": {"type": "number", "animation": "kotlin.Float"},
                    "steps": {"type": "integer"},
                    "onValueChange": {"type": "actionId"},
                    "modifier": {"type": "modifier"},
                }
            },
            "TextField": {
                "props": {
                    "value": {"type": "string"},
                    "onValueChange": {"type": "actionId"},
                },
                "state": {"kind": "value", "value": "value"},
            },
        }
    )
    census = binding_census(registry)
    assert census["states"] == {"bindable": 1, "held": 1}
    assert census["classes"] == {"binding-protocol": 1}
    assert census["unclassifiedReasons"] == {}
    assert census["props"] == 3


def test_an_unbindable_prop_names_the_converter_it_lacks() -> None:
    """A reason the account can read, not a bare absence."""
    from pycompose_codegen.derive.accounting import binding_census

    registry = _registry(
        components={
            "Surface": {
                "props": {
                    "border": {"type": "value", "valueType": "border"},
                    "shadowElevation": {
                        "type": "dp",
                        "animation": "androidx.compose.ui.unit.Dp",
                    },
                }
            }
        }
    )
    census = binding_census(registry)
    assert census["classes"] == {"binding-protocol": 1}
    assert census["states"] == {"bindable": 1}
