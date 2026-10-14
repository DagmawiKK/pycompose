"""Tests for reading the classpath dump.

The dump is only useful if the wire classification is right, and a wrong
classification does not fail loudly -- a content slot read as a callback becomes
an actionId, and the app renders nothing and nobody knows why until someone taps
the wrong thing. So these tests pin the cases that are easy to get wrong and
that the dump makes easy to get right.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from schema.classpath_dump import (
    Kind,
    Wire,
    _classify,
    _parse,
    composables,
    load,
    summarise,
    wire_type,
)

DUMP = Path("android/build/compose-api")


def param(name: str, type_name: str, required: bool = True, kind: Kind = Kind.VALUE):
    """Build a parameter for a fixture.

    Args:
        name: The parameter name.
        type_name: The rendered Kotlin type.
        required: Whether Compose declares no default for it.
        kind: Its wire classification.

    Returns:
        The parameter.
    """
    from schema.classpath_dump import Parameter

    return Parameter(name=name, type=type_name, kind=kind, required=required)


def write_dump(directory: Path, payload: dict[str, list[str]]) -> Path:
    """Write a one-artifact dump.

    Args:
        directory: Where to write.
        payload: Class name to signatures.

    Returns:
        The directory written.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "material3.json").write_text(json.dumps(payload))
    return directory


# ---------------------------------------------------------------------------
# Content slot versus callback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("type_name", "kind"),
    [
        ("Function0<Unit>", Kind.SLOT),
        ("Function1<RowScope>", Kind.SLOT),
        ("Function1<Boolean>", Kind.CALLBACK),
        ("Function1<TextFieldValue>", Kind.CALLBACK),
        ("String", Kind.VALUE),
        ("Boolean", Kind.VALUE),
        ("Modifier", Kind.VALUE),
        ("Function2", Kind.UNKNOWN),
        ("Map<String, Unit>", Kind.UNKNOWN),
    ],
)
def test_a_parameter_is_classified_by_what_it_carries(
    type_name: str, kind: Kind
) -> None:
    """The distinction the whole approach exists for.

    A `Function0` takes nothing, so there is nothing for the app to report and
    it is content whatever it is called. A scoped `Function1` takes something
    Compose provides, not something the app sends. A plain `Function1` takes a
    value and is a real callback.
    """
    assert _classify(type_name) is kind


def test_a_scoped_lambda_is_content_and_not_a_callback() -> None:
    """Same arity, opposite meaning. This is the trap.

    `RowScope.() -> Unit` and `(Boolean) -> Unit` both arrive as a one-argument
    function type. Mapping both to an actionId would give `Button` a content
    slot the app can "click".
    """
    assert _classify("Function1<RowScope>") is Kind.SLOT
    assert _classify("Function1<Boolean>") is Kind.CALLBACK


def test_a_callback_reports_its_payload() -> None:
    """Dropping the payload compiles and then reports nothing."""
    parsed = _parse("Checkbox(checked: Boolean, onCheckedChange: Function1<Boolean>)")
    assert parsed is not None
    parameters = parsed[1]
    callback = next(p for p in parameters if p.name == "onCheckedChange")
    assert callback.kind is Kind.CALLBACK
    assert callback.payload == "Boolean"


def test_a_slot_has_no_payload() -> None:
    parsed = _parse("Button(onClick: Function0<Unit>, content: Function1<RowScope>)")
    assert parsed is not None
    for parameter in parsed[1]:
        assert parameter.kind is Kind.SLOT
        assert parameter.payload is None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_every_parameter_is_parsed_not_just_the_first() -> None:
    """Anchoring the parameter pattern on ^ and $ finds one parameter.

    That bug made Checkbox appear to have no callback at all, which is a very
    plausible-looking wrong answer rather than an obvious one.
    """
    parsed = _parse(
        "TextField(value: String, onValueChange: Function1<String>, enabled: Boolean)"
    )
    assert parsed is not None
    assert [p.name for p in parsed[1]] == ["value", "onValueChange", "enabled"]


def test_a_signature_with_no_parameters_parses() -> None:
    parsed = _parse("Spacer()")
    assert parsed is not None
    assert parsed[1] == ()


def test_a_signature_that_is_not_one_is_refused() -> None:
    assert _parse("not a signature") is None


# ---------------------------------------------------------------------------
# Overloads
# ---------------------------------------------------------------------------


def test_the_plain_string_overload_is_preferred() -> None:
    """`Text` is overloaded on String and AnnotatedString; an app writes String.

    Most-crossing cannot separate them -- they share every parameter name -- so
    without an explicit preference the choice falls to whichever the dump lists
    first, and that is a decision nobody should inherit.
    """
    directory = write_dump(
        Path("/tmp/pycompose-dump-overload"),
        {
            "androidx.compose.material3.TextKt": [
                "Text(text: AnnotatedString, modifier: Modifier, color: Color)",
                "Text(text: String, modifier: Modifier, color: Color)",
            ]
        },
    )
    found = composables(directory)
    assert found["Text"].parameters[0].type == "String"


def test_the_choice_does_not_depend_on_listing_order() -> None:
    """Reversing the dump must not reverse the answer."""
    forward = write_dump(
        Path("/tmp/pycompose-dump-order-a"),
        {"TextKt": ["Text(text: String)", "Text(text: AnnotatedString)"]},
    )
    backward = write_dump(
        Path("/tmp/pycompose-dump-order-b"),
        {"TextKt": ["Text(text: AnnotatedString)", "Text(text: String)"]},
    )
    assert composables(forward)["Text"].parameters[0].type == "String"
    assert composables(backward)["Text"].parameters[0].type == "String"


def test_the_overload_count_is_kept() -> None:
    directory = write_dump(
        Path("/tmp/pycompose-dump-count"),
        {"TextKt": ["Text(text: String)", "Text(text: AnnotatedString)"]},
    )
    assert composables(directory)["Text"].overloads == 2


def test_overloads_merge_under_one_name() -> None:
    """Five JVM methods, one composable -- or the catalog invents a component."""
    directory = write_dump(
        Path("/tmp/pycompose-dump-merge"),
        {"TextKt": ["Text(text: String)", "Text(text: AnnotatedString)"]},
    )
    assert "Text" in composables(directory)


# ---------------------------------------------------------------------------
# The real dump
# ---------------------------------------------------------------------------


skip_without_dump = pytest.mark.skipif(
    not DUMP.is_dir(),
    reason="run ./gradlew dumpComposeApi first",
)


@skip_without_dump
def test_the_real_dump_has_the_components_this_project_uses() -> None:
    """If any of these is missing, the dump is reading the wrong artifacts."""
    found = composables(DUMP)
    for name in ("Button", "Checkbox", "Text", "TextField", "Card", "Column", "Row"):
        assert name in found, f"{name} missing from the dump"


@skip_without_dump
def test_the_real_dump_does_not_contain_something_the_bom_lacks() -> None:
    """The reason this route exists.

    `TextFieldState` is material3 1.4.0-alpha and the BOM here resolves 1.3.1.
    Its presence would mean the dump came from androidx-main after all, which is
    the failure that blocked the full mirror.
    """
    assert "TextFieldState" not in composables(DUMP)


@skip_without_dump
def test_the_real_dump_separates_slots_from_callbacks_at_scale() -> None:
    """Both kinds must survive; one of them collapsing is the bug."""
    found = composables(DUMP)
    slots = sum(len(c.slots) for c in found.values())
    callbacks = sum(len(c.callbacks) for c in found.values())
    assert slots > 100, f"only {slots} content slots"
    assert callbacks > 50, f"only {callbacks} callbacks"


@skip_without_dump
def test_every_composable_in_the_real_dump_has_a_package() -> None:
    """Without one, no Kotlin import can be generated."""
    for name, entry in composables(DUMP).items():
        assert entry.package, f"{name} has no package"


@skip_without_dump
def test_summarise_runs_against_the_real_dump() -> None:
    assert "composables" in summarise(DUMP)


def test_a_missing_dump_says_so_rather_than_reporting_nothing() -> None:
    """An empty catalog is indistinguishable from a library that declares none."""
    with pytest.raises(FileNotFoundError, match="dumpComposeApi"):
        load(Path("/tmp/pycompose-no-such-dump"))


# ---------------------------------------------------------------------------
# Step 0 -- the dump carries defaults and stability
# ---------------------------------------------------------------------------


def test_a_compose_default_is_read_from_the_signature() -> None:
    """`= default` is how the dump says "the app need not supply this".

    Compose's AARs contain no `$default` synthetic bridges, so presence cannot
    be read from those; it comes from the metadata blob. The *value* is not
    recorded and must not be -- most Compose defaults read ambient state and
    cannot cross a process boundary.
    """
    parsed = _parse("Checkbox(checked: Boolean, enabled: Boolean = default)")
    assert parsed is not None
    _, parameters, _ = parsed
    assert parameters[0].required is True
    assert parameters[1].required is False


def test_the_default_marker_is_not_part_of_the_type() -> None:
    """Otherwise `Boolean = default` becomes a wire type nobody has."""
    parsed = _parse("Text(enabled: Boolean = default)")
    assert parsed is not None
    assert parsed[1][0].type == "Boolean"


def test_an_unreadable_parameter_is_marked_not_guessed() -> None:
    """`Dp`, `TextUnit` and `Long` are all `long` in a JVM descriptor.

    Rendering the descriptor's spelling would type a dimension prop as an
    integer -- quietly wrong rather than absent, which is worse than refusing.
    """
    parsed = _parse("Foo(size: ?long, name: String)")
    assert parsed is not None
    assert parsed[1][0].type == "?long"


def test_stability_markers_are_read_off_the_signature() -> None:
    parsed = _parse(
        "@ExperimentalMaterial3Api Sheet(onDismissRequest: Function0<Unit>)"
    )
    assert parsed is not None
    name, _, markers = parsed
    assert name == "Sheet"
    assert markers == ("ExperimentalMaterial3Api",)


# ---------------------------------------------------------------------------
# Step 1 -- stability and requiredness reach the model
# ---------------------------------------------------------------------------


def test_a_composable_reports_its_experimental_markers() -> None:
    directory = write_dump(
        Path("/tmp/pycompose-dump-stability"),
        {
            "SheetKt": [
                "@ExperimentalMaterial3Api Sheet(onDismissRequest: Function0<Unit>)"
            ],
            "PlainKt": ["Plain(value: String)"],
        },
    )
    found = composables(directory)
    assert found["Sheet"].experimental is True
    assert found["Plain"].experimental is False


def test_a_required_parameter_is_one_without_a_default() -> None:
    directory = write_dump(
        Path("/tmp/pycompose-dump-required"),
        {"CkKt": ["Checkbox(checked: Boolean, enabled: Boolean = default)"]},
    )
    parameters = {p.name: p for p in composables(directory)["Checkbox"].parameters}
    assert parameters["checked"].required is True
    assert parameters["enabled"].required is False


# ---------------------------------------------------------------------------
# Step 2 -- type resolution refuses rather than approximates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("type_name", "wire"),
    [
        ("String", Wire.STRING),
        ("Boolean", Wire.BOOLEAN),
        ("Int", Wire.INTEGER),
        ("Long", Wire.INTEGER),
        ("Float", Wire.NUMBER),
        ("Dp", Wire.DIMENSION),
        ("TextUnit", Wire.DIMENSION),
        ("Color", Wire.COLOR),
        ("TextAlign", Wire.ENUM),
        ("Shape", Wire.ENUM),
        ("PaddingValues", Wire.EDGES),
        ("Brush", Wire.BRUSH),
        ("Modifier", Wire.MODIFIER),
    ],
)
def test_an_expressible_type_maps_to_the_schema_vocabulary(
    type_name: str, wire: Wire
) -> None:
    """The schema's own spelling, so a generated prop drops into an entry."""
    assert wire_type(param("p", type_name)) is wire


@pytest.mark.parametrize(
    "type_name",
    [
        "Animatable",
        "TwoWayConverter",
        "PagerScope",
        "MutableState",
        "AnimationSpec",
        "ProvidableCompositionLocal",
        "DatePickerColors",
    ],
)
def test_an_inexpressible_type_is_refused(type_name: str) -> None:
    """None means no wire representation exists, and that is the honest answer.

    Modelling these would mean inventing a representation for host state the app
    cannot own, and the failure would be a prop that accepts something
    meaningless.
    """
    assert wire_type(param("p", type_name)) is None


def test_an_unreadable_type_is_refused_even_when_its_jvm_shape_looks_fine() -> None:
    """`?long` is not a Long."""
    assert wire_type(param("size", "?long")) is None


def test_slots_and_callbacks_get_their_own_wire_types() -> None:
    assert (
        wire_type(param("content", "Function1<RowScope>", kind=Kind.SLOT))
        is Wire.CONTENT
    )
    assert (
        wire_type(param("onClick", "Function1<Boolean>", kind=Kind.CALLBACK))
        is Wire.ACTION
    )


def test_omitted_props_are_recorded_not_dropped() -> None:
    """The difference between a build error and a prop nobody notices."""
    directory = write_dump(
        Path("/tmp/pycompose-dump-omit"),
        {
            "CarouselKt": [
                "Carousel(state: Animatable, modifier: Modifier = default,"
                " onClick: Function1<Boolean>)"
            ]
        },
    )
    entry = composables(directory)["Carousel"]
    omitted = {p.name for p in entry.omitted}
    assert omitted == {"state"}
    assert "modifier" in {p.name for p in entry.parameters}
    assert "onClick" in {p.name for p in entry.parameters}


def test_every_omitted_prop_is_an_untyped_one() -> None:
    directory = write_dump(
        Path("/tmp/pycompose-dump-omit2"),
        {"XKt": ["X(a: Animatable, b: String, c: PagerScope)"]},
    )
    entry = composables(directory)["X"]
    assert {p.name for p in entry.omitted} == {"a", "c"}
    assert all(wire_type(p) is None for p in entry.omitted)


@skip_without_dump
def test_the_real_dump_separates_omissions_from_read_failures() -> None:
    """Lumping them would make a tooling bug look like a scope decision."""
    text = summarise(DUMP)
    assert "not expressible on the wire" in text
    assert "unread from metadata" in text


@skip_without_dump
def test_no_primitive_survives_as_a_wire_type() -> None:
    """A JVM primitive leaking through means a parameter was never read."""
    for name, entry in composables(DUMP).items():
        for parameter in entry.parameters:
            assert parameter.type not in (
                "long",
                "int",
                "float",
                "double",
                "boolean",
            ), f"{name}.{parameter.name} is a bare JVM primitive"
