"""Converters are a pin fact: the lock records what Compose can animate.

No list of animatable types lives in the generator. Every public property the
pin declares that returns a ``TwoWayConverter`` names one, and every prop
records the type it would be animated as only when such a converter exists and
Python is the value's sole author.
"""

from __future__ import annotations

import json
from pathlib import Path

from pycompose_codegen.derive.classpath_types import KotlinType
from pycompose_codegen.derive.converters import animated_type

LOCK = Path(__file__).resolve().parents[4] / "schema" / "catalog.lock.json"
CATALOG = json.loads(LOCK.read_text())
TWO_WAY = "androidx/compose/animation/core/TwoWayConverter"


def _converter(first: str, classifier: str = TWO_WAY) -> KotlinType:
    """A ``TwoWayConverter<T, V>`` for ``first``."""
    inner = KotlinType(first, False, (), ())
    return KotlinType(classifier, False, (), (("INVARIANT", inner),))


def _declaration(returns: KotlinType) -> object:
    """Just the part ``animated_type`` reads."""
    return type("Declaration", (), {"return_type": returns})()


def test_a_converter_property_names_the_type_it_animates() -> None:
    assert animated_type(_declaration(_converter("kotlin/Float"))) == "kotlin.Float"


def test_a_type_parameter_animates_no_concrete_type() -> None:
    assert animated_type(_declaration(_converter("#0"))) is None


def test_a_colour_space_function_wraps_the_converter_it_returns() -> None:
    converter = _converter("androidx/compose/ui/graphics/Color")
    space = KotlinType(
        "androidx/compose/ui/graphics/colorspace/ColorSpace", False, (), ()
    )
    returns = KotlinType(
        "kotlin/Function1",
        False,
        (),
        (("INVARIANT", space), ("INVARIANT", converter)),
    )
    assert animated_type(_declaration(returns)) == "androidx.compose.ui.graphics.Color"


def test_the_lock_records_every_converter_the_pin_declares() -> None:
    # The pin's public converters: the ten it gives, and no TransformOrigin,
    # whose converter is private.
    assert sorted(CATALOG["converters"]) == [
        "androidx.compose.ui.geometry.Offset",
        "androidx.compose.ui.geometry.Rect",
        "androidx.compose.ui.geometry.Size",
        "androidx.compose.ui.graphics.Color",
        "androidx.compose.ui.unit.Dp",
        "androidx.compose.ui.unit.DpOffset",
        "androidx.compose.ui.unit.IntOffset",
        "androidx.compose.ui.unit.IntSize",
        "kotlin.Float",
        "kotlin.Int",
    ]


def test_every_annotated_prop_names_a_converter_the_pin_declares() -> None:
    converters = CATALOG["converters"]
    for section in ("components", "modifiers"):
        for entry in CATALOG[section].values():
            for prop, spec in entry["props"].items():
                if "animation" in spec:
                    assert spec["animation"] in converters, (entry, prop)


def test_a_prop_a_state_holder_owns_is_not_offered_a_binding() -> None:
    # Python is not the sole author: the user drives these, and reconciling the
    # two is a later protocol rather than a binding.
    assert "animation" not in CATALOG["components"]["Slider"]["props"]["value"]
    assert (
        "animation"
        not in CATALOG["components"]["DatePicker"]["props"]["displayedMonthMillis"]
    )


def test_a_prop_whose_kotlin_type_the_lock_never_states_is_refused() -> None:
    # An integer wire value may be an index, a timestamp or a selection range;
    # the lock states the Kotlin type where it knows it and refuses otherwise.
    assert "animation" not in CATALOG["components"]["TextField"]["props"]["selection"]
    # A held position travels only where its holder drives with a spec and snaps.
    lazy = CATALOG["components"]["LazyColumn"]["props"]["firstVisibleItemIndex"]
    assert "animation" not in lazy
    assert (
        CATALOG["components"]["Column"]["props"]["value"]["animation"] == "kotlin.Int"
    )
