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
    _classify,
    _parse,
    composables,
    load,
    summarise,
)

DUMP = Path("android/build/compose-api")


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
    _, parameters = parsed
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
