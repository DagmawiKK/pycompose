"""The resolved component binding contract: one overlay per entry, never a union.

An entry used to be checked against every parameter name its name appears with
anywhere, so a prop only a sibling overload declares passed. These tests pin
the opposite: the face a generated call passes is derived from the approved
wiring, exactly one pinned declaration must accept it, and a hand-written call
must record the identity it binds.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from test_classpath_dump import (
    DUMP,
    ROOT,
    declaration,
    parameter,
    type_doc,
    write_inventory,
)

PACKAGE = "androidx.compose.material3.test"


def registry(props: dict, children: dict | None = None, **entry: object) -> dict:
    """A one-component catalog shaped like the approved one."""
    return {
        "schemaVersion": "1.0.0",
        "valueTypes": {},
        "components": {
            "Widget": {
                "package": PACKAGE,
                "category": "test",
                "stability": "stable",
                "props": props,
                "children": children or {"allowed": False},
                **entry,
            }
        },
    }


def widget(
    parameters: list[dict],
    jvm: str = "Widget",
    descriptor: str = "(Landroidx/compose/ui/Modifier;)V",
) -> dict:
    """One pinned declaration of the synthetic component."""
    return declaration(
        name="Widget",
        package=PACKAGE,
        owner=f"{PACKAGE}.WidgetKt",
        jvm={"name": jvm, "descriptor": descriptor, "matched": True},
        parameters=parameters,
    )


def modifier() -> dict:
    """The native ``Modifier`` parameter every generated call passes."""
    return parameter(
        "modifier", type_doc("androidx/compose/ui/Modifier"), has_default=True
    )


def string(name: str) -> dict:
    """A required ``String`` parameter."""
    return parameter(name, type_doc("kotlin/String"))


def resolve_one(tmp_path: Path, records: list[dict], props: dict, **entry: object):
    """Resolve the synthetic component against one synthetic inventory."""
    from tools.schema.classpath_dump import inventory
    from tools.schema.component_binding import resolutions

    write_inventory(tmp_path, records)
    return resolutions(registry(props, **entry), inventory(tmp_path))[0]


def test_the_face_travels_under_native_names_and_holds_children() -> None:
    from tools.schema.component_face import face

    entry = registry(
        {
            "label": {"type": "string", "required": True},
            "onClick": {"type": "actionId", "required": True},
        },
        children={"allowed": True, "kind": "content"},
    )["components"]["Widget"]
    derived = face(
        entry,
        {"valueTypes": {}},
        frozenset({"modifier", "label", "onClick", "content"}),
    )
    assert [argument.name for argument in derived.arguments] == [
        "content",
        "label",
        "modifier",
        "onClick",
    ]
    assert derived.anonymous is False
    assert derived.host == ()
    assert derived.problems == ()


def test_a_reshaped_prop_the_pin_never_names_is_host_consumed() -> None:
    from tools.schema.component_face import face

    entry = registry(
        {"resource": {"type": "string", "required": True}},
        reshaped=["resource"],
    )["components"]["Widget"]
    derived = face(entry, {"valueTypes": {}}, frozenset({"modifier"}))
    assert [argument.name for argument in derived.arguments] == ["modifier"]
    assert derived.host == ("resource",)


def test_a_reshaped_prop_the_pin_names_is_forwarded() -> None:
    from tools.schema.component_face import face

    entry = registry(
        {"onPress": {"type": "actionId", "required": True}},
        reshaped=["onPress"],
    )["components"]["Widget"]
    derived = face(entry, {"valueTypes": {}}, frozenset({"modifier", "onPress"}))
    assert [argument.name for argument in derived.arguments] == ["modifier", "onPress"]
    assert derived.host == ()


def test_one_overload_is_selected_by_forwarded_names_and_required_parameters(
    tmp_path: Path,
) -> None:
    old = widget(
        [modifier(), string("label"), parameter("extra", type_doc("kotlin/Boolean"))],
        jvm="Widget-old",
    )
    new = widget([modifier(), string("label")], jvm="Widget-new")
    result = resolve_one(
        tmp_path,
        [old, new],
        props={"label": {"type": "string", "required": True}},
    )
    assert result.mode == "derived"
    assert result.source is not None and result.source["jvmName"] == "Widget-new"
    assert result.errors == ()
    assert any("source is not recorded" in fact for fact in result.differences)


def test_a_prop_only_a_sibling_declares_cannot_widen_the_union(
    tmp_path: Path,
) -> None:
    first = widget(
        [modifier(), string("label"), string("trailingIcon")], jvm="Widget-first"
    )
    second = widget(
        [modifier(), string("label"), string("leadingIcon")], jvm="Widget-second"
    )
    result = resolve_one(
        tmp_path,
        [first, second],
        props={
            "label": {"type": "string", "required": True},
            "trailingIcon": {"type": "string", "required": True},
        },
    )
    # Both overloads carry ``trailingIcon``'s neighbours; only one carries the
    # prop itself, so the entry binds one signature rather than a union of two.
    assert result.mode == "derived"
    assert result.source is not None and result.source["jvmName"] == "Widget-first"

    mismatched = resolve_one(
        tmp_path,
        [first, second],
        props={
            "trailingIcon": {"type": "string", "required": True},
            "leadingIcon": {"type": "string", "required": True},
        },
    )
    assert mismatched.mode == "refused"
    assert any("no pinned overload accepts" in error for error in mismatched.errors)


def test_two_accepting_overloads_are_refused_not_guessed(tmp_path: Path) -> None:
    first = widget([modifier(), string("label")], jvm="Widget-one")
    second = widget([modifier(), string("label")], jvm="Widget-two")
    result = resolve_one(
        tmp_path,
        [first, second],
        props={"label": {"type": "string", "required": True}},
    )
    assert result.mode == "refused"
    assert any(
        "2 pinned overloads accept" in error for error in result.errors
    ), result.errors


def test_a_recorded_source_must_equal_the_selected_overload(tmp_path: Path) -> None:
    record = widget([modifier(), string("label")], jvm="Widget")
    result = resolve_one(
        tmp_path,
        [record],
        props={"label": {"type": "string", "required": True}},
        source={
            "artifact": "androidx.compose.material3:material3-android:1.4.0",
            "owner": "androidx.compose.material3.test.WidgetKt",
            "name": "Widget",
            "jvmName": "Widget-old",
            "descriptor": "(Landroidx/compose/ui/Modifier;)V",
        },
    )
    assert result.mode == "derived"
    assert any(
        "differs from the pinned overload" in error for error in result.errors
    ), result.errors


def test_a_schema_alias_resolves_through_its_native_name(tmp_path: Path) -> None:
    """A schema alias keeps its own key while the source selects the pin."""
    from tools.schema.classpath_dump import inventory
    from tools.schema.component_binding import resolutions

    record = widget([modifier(), string("label")], jvm="Widget")
    catalog = registry(
        {"label": {"type": "string", "required": True}},
        source={
            "artifact": "androidx.compose.material3:material3-android:1.4.0",
            "owner": f"{PACKAGE}.WidgetKt",
            "name": "Widget",
            "jvmName": "Widget",
            "descriptor": "(Landroidx/compose/ui/Modifier;)V",
        },
    )
    catalog["components"]["AliasedWidget"] = catalog["components"].pop("Widget")
    write_inventory(tmp_path, [record])

    result = resolutions(catalog, inventory(tmp_path))[0]
    assert result.name == "AliasedWidget"
    assert result.mode == "derived"
    assert result.source is not None and result.source["name"] == "Widget"
    assert result.errors == ()


def test_a_manual_adapter_claims_no_identity(tmp_path: Path) -> None:
    record = widget([modifier(), string("label")], jvm="Widget")
    result = resolve_one(
        tmp_path,
        [record],
        props={"label": {"type": "string", "required": True}},
        adapter="manual",
    )
    assert result.mode == "manual"
    assert result.source is None and result.recorded is None
    assert result.errors == ()


def test_an_anchored_wrapper_verifies_its_recorded_identity(tmp_path: Path) -> None:
    painter = widget(
        [
            modifier(),
            parameter(
                "painter", type_doc("androidx/compose/ui/graphics/painter/Painter")
            ),
        ],
        jvm="Widget-painter",
    )
    props = {"resource": {"type": "string", "required": True}}
    anchored = resolve_one(
        tmp_path,
        [painter],
        props=props,
        reshaped=["resource"],
        wrapper="ResourceImage",
        source={
            "artifact": "androidx.compose.material3:material3-android:1.4.0",
            "owner": "androidx.compose.material3.test.WidgetKt",
            "name": "Widget",
            "jvmName": "Widget-painter",
            "descriptor": "(Landroidx/compose/ui/Modifier;)V",
        },
    )
    assert anchored.mode == "anchored"
    assert anchored.errors == ()

    refused = resolve_one(
        tmp_path,
        [painter],
        props=props,
        reshaped=["resource"],
        wrapper="ResourceImage",
        source={
            "artifact": "androidx.compose.material3:material3-android:1.4.0",
            "owner": "androidx.compose.material3.test.WidgetKt",
            "name": "Widget",
            "jvmName": "Widget-gone",
            "descriptor": "(Landroidx/compose/ui/Modifier;)V",
        },
    )
    assert refused.mode == "anchored"
    assert any("not pinned" in error for error in refused.errors)

    orphan = resolve_one(
        tmp_path,
        [painter],
        props=props,
        reshaped=["resource"],
        wrapper="ResourceImage",
    )
    assert orphan.mode == "refused"
    assert any("record the overload" in error for error in orphan.errors), orphan.errors


def test_resolutions_are_deterministic(tmp_path: Path) -> None:
    from tools.schema.classpath_dump import inventory
    from tools.schema.component_binding import resolutions

    write_inventory(tmp_path, [widget([modifier(), string("label")], jvm="Widget-a")])
    found = inventory(tmp_path)
    catalog = registry({"label": {"type": "string", "required": True}})
    assert resolutions(catalog, found) == resolutions(catalog, found)


def test_the_checker_reports_an_unrecorded_component(tmp_path: Path) -> None:
    from tools.composegen.check import compare
    from tools.schema.classpath_dump import inventory

    write_inventory(tmp_path, [widget([modifier(), string("label")])])
    errors = compare(
        registry({"label": {"type": "string", "required": True}}), inventory(tmp_path)
    )
    assert len(errors) == 1 and "source is not recorded" in errors[0], errors


def test_the_checker_reports_a_prop_no_single_overload_declares(
    tmp_path: Path,
) -> None:
    from tools.composegen.check import compare
    from tools.schema.classpath_dump import inventory

    write_inventory(tmp_path, [widget([modifier(), string("label")])])
    errors = compare(
        registry(
            {
                "label": {"type": "string", "required": True},
                "ghost": {"type": "string", "required": True},
            }
        ),
        inventory(tmp_path),
    )
    assert "Widget.ghost: no parameter in any pinned overload" in errors, errors


def test_every_approved_component_resolves_to_one_pinned_overload(
    native_document,
) -> None:
    from tools.schema.classpath_dump import inventory
    from tools.schema.component_binding import resolutions

    assert native_document["artifacts"]
    catalog = json.loads((ROOT / "schema/catalog.lock.json").read_text())
    results = resolutions(catalog, inventory(DUMP))
    # Every catalog component resolves in exactly one mode; how many land in
    # each follows policy, so only the partition is asserted.
    modes = Counter(result.mode for result in results)
    assert set(modes) <= {"derived", "anchored", "manual"}
    assert sum(modes.values()) == len(catalog["components"])
    assert [result.name for result in results if result.errors] == []
    assert [result.name for result in results if result.differences] == []
    drifted = [
        result.name
        for result in results
        if result.mode == "derived" and result.source != result.recorded
    ]
    assert drifted == []


def test_the_resolved_face_is_the_generated_call(native_document) -> None:
    from pycompose.schema.codegen.adapters import render
    from tools.schema.classpath_dump import inventory
    from tools.schema.component_binding import resolutions

    assert native_document["artifacts"]
    catalog = json.loads((ROOT / "schema/catalog.lock.json").read_text())
    checked = skipped = 0
    for result in resolutions(catalog, inventory(DUMP)):
        entry = catalog["components"][result.name]
        if entry.get("wrapper") or entry.get("adapter") == "manual":
            skipped += 1
            continue
        block = render(result.name, entry)
        arguments = set(re.findall(r"^\s{20,}(?!val\b)(\w+) = ", block, re.MULTILINE))
        assert arguments == {
            argument.name for argument in result.face.arguments
        }, result.name
        checked += 1
    assert checked and checked + skipped == len(catalog["components"])


def test_the_checker_is_green_on_the_approved_catalog(native_document) -> None:
    from tools.composegen.check import compare
    from tools.schema.classpath_dump import inventory

    assert native_document["artifacts"]
    catalog = json.loads((ROOT / "schema/catalog.lock.json").read_text())
    assert compare(catalog, inventory(DUMP)) == []
