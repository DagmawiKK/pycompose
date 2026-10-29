"""Value construction and canonical IR at the Python public boundary."""

import json
from dataclasses import replace

import jsonschema
import pytest

from pycompose.errors import IrValidationError
from pycompose.state import State
from pycompose.ui import Text
from pycompose.wire import emit_ir, to_json_bytes, validate_ir


def test_color_is_data_and_reaches_canonical_ir() -> None:
    from pycompose.values import Color

    color = Color(0xFF336699)
    assert color == {"type": "Color", "color": 4281558681}
    node = Text(id="title", text="Hello", color=color)
    snapshot = json.loads(to_json_bytes(emit_ir(State(root=node), "1.11.0")))
    assert snapshot["root"]["props"]["color"] == color


def test_tagged_values_require_new_schema_while_legacy_colors_still_work() -> None:
    from pycompose.values import Color

    tagged = emit_ir(
        State(root=Text(id="t", text="Hi", color=Color(0xFF000000))), "1.11.0"
    )
    with pytest.raises(IrValidationError, match="newer schema"):
        validate_ir(replace(tagged, schema_version="1.10.0"))
    legacy = emit_ir(State(root=Text(id="t", text="Hi", color="#000000")), "1.0.0")
    assert validate_ir(legacy).snapshot is legacy


def test_text_style_keeps_unit_and_null_distinctions() -> None:
    from pycompose.values import Dp, Em, Sp, TextStyle

    style = TextStyle(font_size=Sp(22), letter_spacing=Em(0.1), font_family=None)
    assert style == {
        "type": "TextStyle",
        "fontSize": {"type": "Sp", "value": 22},
        "letterSpacing": {"type": "Em", "value": 0.1},
        "fontFamily": None,
    }
    assert TextStyle() == {"type": "TextStyle"}
    assert (
        Text(id="t", text="Hello", style=style).props["style"]["fontSize"]["type"]
        == "Sp"
    )
    with pytest.raises(IrValidationError):
        TextStyle(font_size=Dp(22))


def test_recursive_brushes_validate_before_reaching_native_code() -> None:
    from pycompose.values import Color, Offset, horizontalGradient, linearGradient

    colors = [Color(0xFFFF0000), Color(0xFF0000FF)]
    brush = horizontalGradient(colors)
    assert brush == {"type": "horizontalGradient", "colors": colors}
    assert linearGradient(colors, start=Offset(0, 0))["start"] == {
        "type": "Offset",
        "x": 0,
        "y": 0,
    }
    colors.clear()
    assert len(brush["colors"]) == 2
    for invalid in ([], [Color(0)], [Color(0), {"type": "Dp", "value": 5}]):
        with pytest.raises(IrValidationError):
            horizontalGradient(invalid)


def test_shapes_and_edges_are_typed_records_not_universal_enums() -> None:
    from pycompose.ui import Modifier
    from pycompose.values import (
        Color,
        Dp,
        PaddingValues,
        RoundedCornerShape,
        SolidColor,
        WindowInsets,
    )

    modifier = (
        Modifier()
        .padding(PaddingValues(start=Dp(4), top=Dp(6)))
        .size(Dp(80), Dp(40))
        .clip(RoundedCornerShape(Dp(8)))
        .background(SolidColor(Color(0xFF336699)))
        .window_insets_padding(WindowInsets(left=Dp(2)))
    )
    node = Text(id="t", text="Hi", modifier=modifier)
    assert validate_ir(emit_ir(State(root=node), "1.11.0")).snapshot.root.type == "Text"
    with pytest.raises(IrValidationError):
        PaddingValues(start=Color(0))


def test_theme_references_remain_symbolic_in_canonical_ir() -> None:
    from pycompose.values import ThemeColor, ThemeTypography

    node = Text(
        id="t",
        text="Hello",
        color=ThemeColor("primary"),
        style=ThemeTypography("titleLarge"),
    )
    wire = to_json_bytes(emit_ir(State(root=node), "1.11.0"))
    assert b'"color":{"name":"primary","type":"ThemeColor"}' in wire
    with pytest.raises(IrValidationError):
        ThemeColor("notAThemeToken")


def test_the_icon_vocabulary_accepts_only_labels_the_pin_carries() -> None:
    from pycompose.values import materialIcon

    icon = materialIcon(name="AutoMirrored.Filled.ArrowBack")
    assert icon == {"type": "materialIcon", "name": "AutoMirrored.Filled.ArrowBack"}
    # ``Icons.Filled.ArrowBack`` is the deprecated spelling the auto-mirrored
    # twin replaced: offering it would generate a call that warns at every build.
    with pytest.raises(IrValidationError):
        materialIcon(name="Filled.ArrowBack")
    with pytest.raises(IrValidationError):
        materialIcon(name="Filled.NotAnIcon")


def test_component_factories_keep_omission_native() -> None:
    from pycompose.ui import Button
    from pycompose.values import Dp, ThemeColor, buttonColors, buttonElevation

    assert buttonColors() == {"type": "buttonColors"}
    assert buttonElevation() == {"type": "buttonElevation"}
    node = Button(
        id="b",
        text="Save",
        on_click="increment",
        colors=buttonColors(container_color=ThemeColor("tertiary")),
        elevation=buttonElevation(default_elevation=Dp(6)),
    )
    assert (
        validate_ir(emit_ir(State(root=node), "1.11.0")).snapshot.root.type == "Button"
    )


@pytest.mark.parametrize("value", [True, -1, 4294967296, 1.5, "#FF000000"])
def test_color_requires_unsigned_argb_bits(value: object) -> None:
    from pycompose.values import Color

    with pytest.raises(IrValidationError):
        Color(value)


@pytest.mark.parametrize(
    "value", [True, float("nan"), float("inf"), 1e39, 1e-50, 10**400]
)
def test_float_wrappers_reject_non_native_numbers(value: object) -> None:
    from pycompose.values import Dp

    with pytest.raises(IrValidationError):
        Dp(value)


def test_layout_rejects_negative_dimensions_before_rendering() -> None:
    from pycompose.ui import Modifier
    from pycompose.values import Dp, PaddingValues

    assert Dp(-2)["value"] == -2  # Dp itself can be signed, layout constraints cannot.
    with pytest.raises(IrValidationError):
        Modifier().size(Dp(-2))
    with pytest.raises(IrValidationError):
        PaddingValues(start=Dp(-2))


def test_generated_json_schema_agrees_on_recursive_and_versioned_values() -> None:
    from pathlib import Path

    from pycompose.ui import Modifier
    from pycompose.values import Dp, Sp, TextStyle

    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "schema/ir.schema.json").read_text()
    )
    node = Text(
        id="t",
        text="Hello",
        style=TextStyle(font_size=Sp(20)),
        modifier=Modifier().size(Dp(80)),
    )
    document = json.loads(to_json_bytes(emit_ir(State(root=node), "1.11.0")))
    jsonschema.validate(document, schema)
    document["schemaVersion"] = "1.10.0"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, schema)
    del document["root"]["props"]["style"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, schema)


def test_nullable_component_props_keep_absent_null_and_value() -> None:
    from pycompose.material3 import Button as GeneratedButton
    from pycompose.ui import Button
    from pycompose.values import buttonElevation

    for component in (Button, GeneratedButton):
        omitted = component(id="b", text="Save", on_click="increment")
        disabled = component(id="b", text="Save", on_click="increment", elevation=None)
        supplied = component(
            id="b", text="Save", on_click="increment", elevation=buttonElevation()
        )
        assert "elevation" not in omitted.props
        assert disabled.props["elevation"] is None
        assert supplied.props["elevation"]["type"] == "buttonElevation"


@pytest.mark.parametrize("dimension", [1e39, 1e-50])
def test_legacy_dimensions_cannot_bypass_native_float_constraints(
    dimension: float,
) -> None:
    from pycompose.ui import Modifier

    with pytest.raises(IrValidationError):
        Modifier().size(dimension)


def test_float_boundaries_preserve_integer_precision_before_narrowing() -> None:
    from pycompose.values import Dp

    with pytest.raises(IrValidationError):
        Dp(340282346638528859811704183484516925441)
    assert Dp(3.4028234663852886e38)["value"] == 3.4028234663852886e38


def test_enum_border_and_annotated_families_validate_before_native_code() -> None:
    from pycompose.core.values import validate_value
    from pycompose.values import (
        DEFINITIONS,
        AnnotatedString,
        BorderStroke,
        Color,
        Dp,
        SolidColor,
        ToggleableState,
    )

    assert AnnotatedString(text="Hi") == {"type": "AnnotatedString", "text": "Hi"}
    assert ToggleableState(name="On") == {"type": "ToggleableState", "name": "On"}
    assert BorderStroke(width=Dp(2), brush=SolidColor(value=Color(0xFF000000))) == {
        "type": "BorderStroke",
        "width": {"type": "Dp", "value": 2},
        "brush": {
            "type": "SolidColor",
            "value": {"type": "Color", "color": 4278190080},
        },
    }
    with pytest.raises(IrValidationError, match="unknown native constant"):
        ToggleableState(name="Maybe")
    with pytest.raises(IrValidationError, match="missing value field"):
        validate_value(
            {"type": "BorderStroke", "width": Dp(2)}, "BorderStroke", DEFINITIONS
        )
    with pytest.raises(IrValidationError, match="wrong value family"):
        BorderStroke(width=Color(0xFF000000), brush=SolidColor(value=Color(0xFFFFFFFF)))
