"""The re-approval workflow: refresh, marker evidence and staged drift."""

from __future__ import annotations

import json

from test_classpath_dump import DUMP, ROOT


def test_refresh_rebinds_the_whole_catalog_without_hand_edits(native_document) -> None:
    from pycompose.compiler.check import compare_values
    from pycompose.compiler.classpath_dump import inventory, source_defaults
    from pycompose.compiler.propose import refresh

    assert native_document["provenance"]["compiler"] == "2.4.21"
    found = inventory(DUMP)
    evidence = source_defaults(DUMP)
    registry = json.loads((ROOT / "schema/catalog.lock.json").read_text())
    results = refresh(found, evidence, registry)
    derived = [item for item in results if "proposal" in item]
    # Every approved binding carrying an artifact source is re-derived, not
    # silently skipped; a language-level source is approved policy that no
    # pin can reproduce (the range descriptor, ADR-0017 decision 5).
    assert {item["name"] for item in derived} == {
        name
        for name, spec in registry["valueTypes"].items()
        if "family" in spec and "source" in spec and "language" not in spec["source"]
    }
    for item in derived:
        approved = registry["valueTypes"][item["name"]]
        # A refresh reproduces the approved compiler-resolved facts exactly;
        # semantic policy such as ARGB bounds is preserved, not regenerated.
        assert item["proposal"] == approved
    # Membership is checked above; the length adds that refresh() skips nothing.
    assert len(derived) == len(results)
    specs = {item["name"]: item["proposal"] for item in derived}
    assert specs["RoundedCornerShape"]["parameters"]["size"]["valueType"] == "Dp"
    assert specs["CutCornerShape"]["parameters"]["size"]["valueType"] == "Dp"
    assert specs["SolidColor"]["kotlinType"] == "androidx.compose.ui.graphics.Brush"
    # 1.4.0 stabilized the date-picker colours factory.
    assert "optIn" not in specs["datePickerColors"]
    assert "optIn" not in specs["checkboxColors"]
    assert specs["TimePickerLayoutType"]["optIn"] == [
        "androidx.compose.material3.ExperimentalMaterial3Api"
    ]
    assert len(specs["ThemeColor"]["parameters"]["name"]["values"]) == 48
    assert len(specs["ThemeTypography"]["parameters"]["name"]["values"]) == 15
    assert len(specs["ThemeShape"]["parameters"]["name"]["values"]) == 5
    assert len(specs["FontFamily"]["parameters"]["name"]["values"]) == 5
    assert list(specs["TextStyle"]["parameters"]) == [
        "color",
        "fontSize",
        "letterSpacing",
        "fontFamily",
        "fontWeight",
    ]
    assert len(specs["TextStyle"]["omitted"]) == 19
    for name in ("horizontalGradient", "verticalGradient", "linearGradient"):
        assert specs[name]["parameters"]["colors"]["items"]["valueType"] == "Color"
        assert specs[name]["omitted"]["tileMode"]["hasDefault"] is True
    assert "defaultNative" not in json.dumps(specs)
    assert compare_values(registry, found, evidence) == []


def pinned_source(artifact: str) -> dict[str, str]:
    """One source identity, pinned to one artifact coordinate."""
    return {
        "artifact": artifact,
        "owner": "androidx.compose.material3.ButtonDefaults",
        "name": "buttonColors",
        "jvmName": "buttonColors-ro_MJ88",
        "descriptor": (
            "(JJJJLandroidx/compose/runtime/Composer;II)"
            "Landroidx/compose/material3/ButtonColors;"
        ),
    }


def colors_binding(artifact: str) -> dict[str, object]:
    """One minimal approved factory binding at a given pin."""
    return {
        "family": "ButtonColors",
        "kind": "factory",
        "source": pinned_source(artifact),
        "parameters": {
            "containerColor": {
                "type": "value",
                "valueType": "Color",
                "default": {
                    "kind": "property",
                    "symbol": (
                        "androidx.compose.ui.graphics.Color.Companion.Unspecified"
                    ),
                },
            }
        },
    }


def vocabulary_binding(
    artifact: str, values: list[str], owners: dict[str, str]
) -> dict[str, object]:
    """One minimal approved member vocabulary at a given pin."""
    return {
        "family": "Color",
        "kind": "constant",
        "source": pinned_source(artifact),
        "parameters": {"name": {"type": "constant", "values": values}},
        "native": {"owners": owners},
    }


def test_stage_applies_mechanical_drift_and_holds_decisions() -> None:
    from pycompose.compiler.propose import stage

    colors = colors_binding("androidx.compose.material3:material3-android:1.3.1")
    checkbox = {**colors_binding("androidx.compose.material3:material3-android:1.3.1")}
    checkbox["family"] = "CheckboxColors"
    vocabulary = vocabulary_binding(
        "androidx.compose.material3:material3-android:1.3.1",
        ["background"],
        {"background": "materialTheme"},
    )
    # The approved entry requires a marker the pin later stabilized away.
    vocabulary["optIn"] = ["androidx.compose.material3.ExperimentalMaterial3Api"]
    registry = {
        "valueTypes": {
            "buttonColors": colors,
            "checkboxColors": checkbox,
            "ThemeColor": vocabulary,
        }
    }
    proposals = [
        {
            "name": "buttonColors",
            "proposal": {
                **colors,
                # Required markers are derived evidence: the pin stabilized
                # the factory, so the tool restates the set without review.
                "optIn": ["androidx.compose.material3.ExperimentalMaterial3Api"],
                "source": pinned_source(
                    "androidx.compose.material3:material3-android:1.4.0"
                ),
            },
        },
        # A release may add a role and its holder; that is mechanical. A
        # changed compiler-resolved default is a decision, so it is held back.
        {
            "name": "ThemeColor",
            "proposal": vocabulary_binding(
                "androidx.compose.material3:material3-android:1.4.0",
                ["background", "surfaceTint"],
                {"background": "materialTheme", "surfaceTint": "roles"},
            ),
        },
        {
            "name": "checkboxColors",
            "proposal": {
                **checkbox,
                "source": pinned_source(
                    "androidx.compose.material3:material3-android:1.4.0"
                ),
                "parameters": {
                    "containerColor": {
                        "type": "value",
                        "valueType": "Color",
                        "default": {
                            "kind": "property",
                            "symbol": (
                                "androidx.compose.material3" ".CheckboxDefaults.Checked"
                            ),
                        },
                    }
                },
            },
        },
        {"name": "missingColors", "unsupported": "no public callable"},
    ]
    candidate, staged, review = stage(registry, proposals)
    assert staged == ["buttonColors", "ThemeColor"]
    assert candidate["valueTypes"]["buttonColors"]["source"]["artifact"].endswith(
        "1.4.0"
    )
    assert candidate["valueTypes"]["buttonColors"]["parameters"] == colors["parameters"]
    assert candidate["valueTypes"]["buttonColors"]["optIn"] == [
        "androidx.compose.material3.ExperimentalMaterial3Api"
    ]
    assert candidate["valueTypes"]["ThemeColor"]["parameters"]["name"]["values"] == [
        "background",
        "surfaceTint",
    ]
    assert candidate["valueTypes"]["ThemeColor"]["native"]["owners"] == {
        "background": "materialTheme",
        "surfaceTint": "roles",
    }
    # A stabilization removes the field outright; it is never staged as null.
    assert "optIn" not in candidate["valueTypes"]["ThemeColor"]
    # A family under review keeps every approved field, including its stale pin.
    assert (
        candidate["valueTypes"]["checkboxColors"]
        == registry["valueTypes"]["checkboxColors"]
    )
    # The approved registry itself is never mutated.
    assert registry["valueTypes"]["buttonColors"]["source"]["artifact"].endswith(
        "1.3.1"
    )
    assert any(
        note.startswith("checkboxColors: parameters.containerColor.default.symbol")
        for note in review
    )
    assert any(note.startswith("missingColors: no public callable") for note in review)


def test_stage_refuses_vocabulary_removals_and_moved_identities() -> None:
    from pycompose.compiler.propose import stage

    vocabulary = vocabulary_binding(
        "androidx.compose.material3:material3-android:1.3.1",
        ["background", "surface"],
        {"background": "materialTheme", "surface": "materialTheme"},
    )
    colors = colors_binding("androidx.compose.material3:material3-android:1.3.1")
    registry = {"valueTypes": {"ThemeColor": vocabulary, "buttonColors": colors}}
    proposals = [
        {
            "name": "ThemeColor",
            "proposal": vocabulary_binding(
                "androidx.compose.material3:material3-android:1.4.0",
                ["background"],
                {"background": "materialTheme"},
            ),
        },
        {
            "name": "buttonColors",
            "proposal": {
                **colors,
                "source": {
                    **pinned_source(
                        "androidx.compose.material3:material3-android:1.4.0"
                    ),
                    "jvmName": "buttonColors-other",
                },
            },
        },
    ]
    candidate, staged, review = stage(registry, proposals)
    assert staged == []
    assert candidate == registry
    assert any(
        note.startswith("ThemeColor: native.owners.surface differs (+1 more)")
        for note in review
    )
    assert any("buttonColors: source.jvmName" in note for note in review)


def test_stage_cannot_target_the_approved_schema(tmp_path, monkeypatch, capsys) -> None:
    from pycompose.compiler import propose

    schema = tmp_path / "components.json"
    schema.write_text(json.dumps({"schemaVersion": "1.0.0", "valueTypes": {}}) + "\n")
    original = schema.read_bytes()
    linked = tmp_path / "linked.json"
    linked.symlink_to(schema)
    monkeypatch.setattr(propose, "inventory", lambda _directory: object())
    monkeypatch.setattr(
        "pycompose.compiler.classpath_dump.source_defaults", lambda _directory: {}
    )
    assert (
        propose.main(["--refresh", "--schema", str(schema), "--stage", str(linked)])
        == 2
    )
    assert "cannot be the approved schema" in capsys.readouterr().err
    assert schema.read_bytes() == original


def test_opt_in_evidence_comes_from_the_pin(native_document) -> None:
    from pycompose.compiler.classpath_dump import (
        inventory,
        opt_in_index,
        opt_in_markers,
        required_opt_ins,
    )

    assert native_document["provenance"]["compiler"] == "2.4.21"
    found = inventory(DUMP)
    markers = opt_in_markers(found)
    index = opt_in_index(found)
    # The pin declares its own opt-in markers; nothing here is listed by hand.
    assert "androidx.compose.material3.ExperimentalMaterial3Api" in markers
    assert "kotlin.RequiresOptIn" not in markers
    experimental = next(
        declaration
        for declaration in found.declarations
        if declaration.owner == "androidx.compose.material3.TooltipDefaults"
        and declaration.name == "richTooltipColors"
    )
    stable = next(
        declaration
        for declaration in found.declarations
        if declaration.owner == "androidx.compose.material3.CheckboxDefaults"
        and declaration.name == "colors"
        and declaration.parameters
    )
    assert required_opt_ins(experimental, index) == {
        "androidx.compose.material3.ExperimentalMaterial3Api"
    }
    assert required_opt_ins(stable, index) == set()
    # A type in the signature gates the call site exactly like an annotation
    # on the declaration: the 1.4.0 app-bar overloads take a scroll behaviour
    # that is itself experimental, and the generated call needs the marker.
    app_bar = next(
        declaration
        for declaration in found.declarations
        if declaration.owner == "androidx.compose.material3.AppBarKt"
        and declaration.name == "LargeTopAppBar"
        and any(
            parameter.name == "collapsedHeight" for parameter in declaration.parameters
        )
    )
    assert "androidx.compose.material3.ExperimentalMaterial3Api" not in (
        app_bar.annotations
    )
    assert required_opt_ins(app_bar, index) == {
        "androidx.compose.material3.ExperimentalMaterial3Api"
    }


def test_a_language_level_family_is_reviewed_not_re_derived(native_document) -> None:
    """The range descriptor pins no artifact; its citation is approved policy.

    ``ClosedFloatingPointRange`` has no factory to pin (ADR-0017 decision 5),
    so the family is skipped by re-derivation and stays exactly as approved,
    and the drift check stays silent about it rather than inventing a source
    the compiler never resolved.
    """
    from test_value_codegen import RANGE_FAMILY

    from pycompose.compiler.check import compare_values
    from pycompose.compiler.classpath_dump import inventory, source_defaults
    from pycompose.compiler.propose import refresh

    assert native_document["provenance"]["compiler"] == "2.4.21"
    found = inventory(DUMP)
    evidence = source_defaults(DUMP)
    registry = json.loads((ROOT / "schema/catalog.lock.json").read_text())
    registry["valueTypes"]["Range"] = json.loads(json.dumps(RANGE_FAMILY))
    results = refresh(found, evidence, registry)
    assert "Range" not in {item["name"] for item in results}
    assert compare_values(registry, found, evidence) == []
