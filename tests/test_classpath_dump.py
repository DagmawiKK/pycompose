"""Behavioral tests at the artifact extraction and public inventory seams."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

DUMP = Path("android/build/compose-api")
ARTIFACT = "androidx.compose.material3:material3-android:1.3.1"
ROOT = Path(__file__).resolve().parents[1]


def type_doc(name: str, *arguments: dict, annotations: tuple[str, ...] = ()):
    return {
        "classifier": name,
        "nullable": False,
        "annotations": list(annotations),
        "suspend": False,
        "arguments": [{"variance": "INVARIANT", "type": a} for a in arguments],
    }


def declaration(name: str = "Text", descriptor: str = "signature", **changes):
    record = {
        "artifact": ARTIFACT,
        "owner": "androidx.compose.material3.TextKt",
        "package": "androidx.compose.material3",
        "name": name,
        "visibility": "PUBLIC",
        "classVisibility": "PUBLIC",
        "jvm": {"name": name, "descriptor": descriptor, "matched": True},
        "disposition": "ui",
        "reason": None,
        "composable": True,
        "annotations": {"androidx/compose/runtime/Composable": {}},
        "receiver": None,
        "dispatchReceiver": None,
        "contextReceivers": [],
        "returnType": type_doc("kotlin/Unit"),
        "typeParameters": [],
        "parameters": [],
    }
    return record | changes


def parameter(name: str, value: dict, has_default: bool = False):
    return {"name": name, "type": value, "hasDefault": has_default, "varargType": None}


def class_evidence(**changes):
    record = {
        "artifact": ARTIFACT,
        "owner": "androidx.compose.material3.TextKt",
        "classifier": "androidx.compose.material3.TextKt",
        "package": "androidx.compose.material3",
        "classKind": "FILE_FACADE",
        "classModality": "FINAL",
        "classVisibility": "PUBLIC",
        "classSupertypes": [],
        "annotations": {},
    }
    return record | changes


def write_inventory(directory: Path, records: list[dict], **changes):
    document = {
        "formatVersion": 1,
        "provenance": {
            "configuration": ":renderer:debugCompileClasspath",
            "bom": "2025.01.01",
            "compiler": "2.0.21",
            "bomConstraints": {"androidx.compose.material3:material3-android": "1.3.1"},
            "overrides": [],
            "sourceHashes": {
                path.relative_to("android").as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for pattern in (
                    "*.gradle.kts",
                    "*/build.gradle.kts",
                    "gradle/libs.versions.toml",
                    "gradle.properties",
                )
                for path in Path("android").glob(pattern)
            },
        },
        "artifacts": [
            {
                "coordinate": ARTIFACT,
                "sha256": "a" * 64,
                "variant": "androidJvm",
                "file": "material3.aar",
            }
        ],
        "declarations": records,
        "classes": [class_evidence()],
        "diagnostics": [],
    } | changes
    (directory / "inventory.json").write_text(json.dumps(document))
    return document


def test_dump_extracts_exact_public_signatures_and_receivers(native_document) -> None:
    document = native_document
    assert document["formatVersion"] == 1
    assert document["provenance"]["bom"] == "2025.01.01"
    artifacts = {a["coordinate"]: a for a in document["artifacts"]}
    assert ARTIFACT in artifacts
    assert all(len(a["sha256"]) == 64 for a in artifacts.values())
    public = [d for d in document["declarations"] if d["disposition"] == "ui"]
    assert public
    assert all(d["visibility"] == "PUBLIC" for d in public)
    assert all(d["jvm"]["matched"] for d in public)
    scoped = next(d for d in public if d["name"] == "NavigationBarItem")
    assert (
        scoped["receiver"]["classifier"]
        == "androidx/compose/foundation/layout/RowScope"
    )
    assert scoped["parameters"][-1]["name"] == "interactionSource"
    assert scoped["parameters"][-1]["type"]["nullable"] is True
    button = next(d for d in public if d["name"] == "Button")
    click = next(p for p in button["parameters"] if p["name"] == "onClick")
    content = next(p for p in button["parameters"] if p["name"] == "content")
    assert "androidx/compose/runtime/Composable" not in click["type"]["annotations"]
    assert "androidx/compose/runtime/Composable" in content["type"]["annotations"]
    assert content["type"]["arguments"][-1]["type"]["classifier"] == "kotlin/Unit"
    assert (
        artifacts[ARTIFACT]["attributes"]["org.jetbrains.kotlin.platform.type"]
        == "androidJvm"
    )
    properties = [
        d for d in document["declarations"] if d["declarationKind"] == "property"
    ]
    month = next(
        d
        for d in properties
        if d["owner"] == "androidx.compose.material3.DatePickerState"
        and d["name"] == "displayedMonthMillis"
    )
    assert month["accessors"]["getter"]["matched"] is True
    assert month["accessors"]["setter"]["matched"] is True
    assert (
        month["dispatchReceiver"]["classifier"]
        == "androidx/compose/material3/DatePickerState"
    )
    assert month["disposition"] == "support"
    assert any(
        d["declarationKind"] == "constructor"
        and d["owner"] == "androidx.compose.material3.ButtonColors"
        for d in document["declarations"]
    )
    from schema.classpath_dump import inventory

    assert len(inventory(DUMP).ui) == len(public)
    assert document["bytecodeAudit"]["unmatchedTargetMethods"] == []
    assert document["provenance"]["overrides"] == []
    state = next(
        d
        for d in document["declarations"]
        if d["owner"] == "androidx.compose.runtime.State" and d["name"] == "value"
    )
    assert state["returnType"]["classifier"] == "#0"
    assert state["enclosingTypeParameters"][0]["name"] == "T"
    snackbar = next(
        d
        for d in document["declarations"]
        if d["owner"] == "androidx.compose.material3.SnackbarHostState"
        and d["name"] == "currentSnackbarData"
    )
    assert snackbar["accessors"]["getter"]["callable"] is True
    assert snackbar["accessors"]["setter"]["visibility"] == "PRIVATE"
    assert snackbar["accessors"]["setter"]["callable"] is False


def test_pinned_overloads_slots_and_scopes_survive_reading(native_document) -> None:
    from schema.classpath_dump import inventory

    found = inventory(DUMP)
    assert len(found.ui) == sum(
        d["disposition"] == "ui" for d in native_document["declarations"]
    )
    assert {d.name for d in found.ui}.isdisjoint({"MaterialTheme", "ProvideTextStyle"})
    text = [d for d in found.ui if d.name == "Text"]
    assert {d.parameters[0].type.classifier for d in text} == {
        "kotlin/String",
        "androidx/compose/ui/text/AnnotatedString",
    }
    basic = [
        d
        for d in found.declarations
        if d.name == "BasicText" and d.disposition == "support"
    ]
    assert len(basic) == 2
    assert all("minLines" in {p.name for p in d.parameters} for d in basic)
    progress = [d for d in found.ui if d.name == "LinearProgressIndicator"]
    assert len(progress) == 3
    assert any(
        p.name == "progress" and p.kind.value == "provider"
        for d in progress
        for p in d.parameters
    )
    animation = [
        d
        for d in found.declarations
        if d.name == "AnimatedVisibility" and d.disposition == "support"
    ]
    assert any(
        d.receiver and d.receiver.classifier.endswith("RowScope") for d in animation
    )
    assert any(
        d.receiver and d.receiver.classifier.endswith("ColumnScope") for d in animation
    )
    tooltip = next(d for d in found.ui if d.name == "PlainTooltip")
    assert tooltip.receiver.classifier == "androidx/compose/material3/TooltipScope"
    assert "androidx/compose/material3/ExperimentalMaterial3Api" in tooltip.annotations
    menu = next(d for d in found.ui if d.name == "ExposedDropdownMenu")
    assert (
        menu.dispatch_receiver.classifier
        == "androidx/compose/material3/ExposedDropdownMenuBoxScope"
    )
    primitives = [
        d
        for d in found.ui
        if d.parameters
        and d.parameters[-1].type.classifier in {"kotlin/Int", "kotlin/Boolean"}
    ]
    assert primitives
    deprecated = [
        d
        for d in found.declarations
        if "kotlin/Deprecated" in d.annotations
        and d.annotations["kotlin/Deprecated"].get("replaceWith")
    ]
    assert deprecated
    assert any(
        "expression" in d.annotations["kotlin/Deprecated"]["replaceWith"]["values"]
        for d in deprecated
    )


def test_native_inventory_is_byte_stable(native_document) -> None:
    before = (DUMP / "inventory.json").read_bytes()
    result = subprocess.run(
        ["./gradlew", "dumpComposeApi", "--rerun-tasks", "--console=plain"],
        cwd="android",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(before) == native_document
    assert (DUMP / "inventory.json").read_bytes() == before


def test_inventory_retains_all_overloads_and_function_semantics(tmp_path: Path) -> None:
    from schema.classpath_dump import inventory

    unit = type_doc("kotlin/Unit")
    records = [
        declaration(
            descriptor=str(index),
            parameters=[
                parameter("text", value),
                parameter("onClick", type_doc("kotlin/Function0", unit)),
                parameter(
                    "content",
                    type_doc(
                        "kotlin/Function0",
                        unit,
                        annotations=("androidx/compose/runtime/Composable",),
                    ),
                    True,
                ),
                parameter(
                    "progress",
                    type_doc("kotlin/Function0", type_doc("kotlin/Float")),
                    True,
                ),
                parameter(
                    "confirmValueChange",
                    type_doc(
                        "kotlin/Function1",
                        type_doc("kotlin/String"),
                        type_doc("kotlin/Boolean"),
                    ),
                ),
            ],
        )
        for index, value in enumerate(
            (
                type_doc("kotlin/String"),
                type_doc("androidx/compose/ui/text/AnnotatedString"),
            )
        )
    ]
    write_inventory(tmp_path, records)
    found = inventory(tmp_path)
    assert len(found.ui) == 2
    assert {d.parameters[0].type.classifier for d in found.ui} == {
        "kotlin/String",
        "androidx/compose/ui/text/AnnotatedString",
    }
    parameters = {p.name: p for p in found.ui[0].parameters}
    assert parameters["onClick"].kind.value == "callback"
    assert parameters["content"].kind.value == "slot"
    assert parameters["progress"].kind.value == "provider"
    assert parameters["confirmValueChange"].kind.value == "unknown"
    assert parameters["onClick"].required is True
    assert parameters["content"].required is False


def test_value_proposal_derives_an_unused_constructor_without_parameter_policy() -> (
    None
):
    from schema.classpath_dump import Declaration
    from schema.propose import propose_value

    source = Declaration.read(
        declaration(
            name="<init>",
            owner="androidx.compose.ui.geometry.Rect",
            disposition="support",
            composable=False,
            declarationKind="constructor",
            returnType=type_doc("androidx/compose/ui/geometry/Rect"),
            parameters=[
                parameter(name, type_doc("kotlin/Float"))
                for name in ("left", "top", "right", "bottom")
            ],
        )
    )
    proposal = propose_value(source, since="1.11.0", families={})
    assert proposal["parameters"] == {
        name: {"type": "float", "required": True}
        for name in ("left", "top", "right", "bottom")
    }
    assert proposal["native"] == {"call": "androidx.compose.ui.geometry.Rect"}
    assert proposal["family"] == "Rect"


def test_value_proposal_refuses_a_constructor_no_app_can_call() -> None:
    from schema.classpath_dump import Declaration
    from schema.propose import propose_value

    source = Declaration.read(
        declaration(
            name="<init>",
            owner="androidx.compose.ui.graphics.painter.Painter",
            disposition="support",
            composable=False,
            declarationKind="constructor",
            classKind="CLASS",
            classModality="ABSTRACT",
            returnType=type_doc("androidx/compose/ui/graphics/painter/Painter"),
        )
    )
    with pytest.raises(ValueError, match="class cannot be constructed"):
        propose_value(source, since="1.12.0", families={})


def test_member_proposal_reads_enum_entries_as_the_wire_vocabulary(tmp_path) -> None:
    from schema.classpath_dump import inventory
    from schema.propose import propose_members

    write_inventory(
        tmp_path,
        [
            declaration(),
            declaration(
                name="<init>",
                owner="androidx.compose.ui.state.ToggleableState",
                disposition="excluded",
                visibility="PRIVATE",
                composable=False,
                declarationKind="constructor",
                classKind="ENUM_CLASS",
                classModality="FINAL",
                enumEntries=["On", "Off", "Indeterminate"],
                returnType=type_doc("androidx/compose/ui/state/ToggleableState"),
            ),
        ],
    )
    spec = propose_members(
        inventory(tmp_path),
        "androidx/compose/ui/state/ToggleableState",
        {
            "family": "ToggleableState",
            "kind": "constant",
            "kotlinType": "androidx.compose.ui.state.ToggleableState",
        },
        since="1.12.0",
    )
    assert spec["parameters"]["name"]["values"] == ["Indeterminate", "Off", "On"]
    assert spec["source"] == {
        "owner": "androidx/compose/ui/state/ToggleableState",
        "members": "enum entries",
    }
    assert spec["native"] == {
        "constantParameter": "name",
        "propertyOwner": "androidx.compose.ui.state.ToggleableState",
    }


def test_icon_proposal_labels_members_by_their_path(tmp_path) -> None:
    from schema.classpath_dump import inventory
    from schema.propose import propose_icons

    image = type_doc("androidx/compose/ui/graphics/vector/ImageVector")
    write_inventory(
        tmp_path,
        [
            declaration(),
            declaration(
                name="Add",
                owner="androidx.compose.material.icons.filled.AddKt",
                package="androidx.compose.material.icons.filled",
                disposition="support",
                composable=False,
                declarationKind="property",
                receiver=type_doc("androidx/compose/material/icons/Icons.Filled"),
                returnType=image,
            ),
            declaration(
                name="Add",
                owner="androidx.compose.material.icons.outlined.AddKt",
                package="androidx.compose.material.icons.outlined",
                disposition="support",
                composable=False,
                declarationKind="property",
                receiver=type_doc("androidx/compose/material/icons/Icons.Outlined"),
                returnType=image,
            ),
            declaration(
                name="ArrowBack",
                owner="androidx.compose.material.icons.automirrored.filled.ArrowBackKt",
                package="androidx.compose.material.icons.automirrored.filled",
                disposition="support",
                composable=False,
                declarationKind="property",
                receiver=type_doc(
                    "androidx/compose/material/icons/Icons.AutoMirrored.Filled"
                ),
                returnType=image,
                annotations={"kotlin/Deprecated": {}},
            ),
            declaration(
                name="Tint",
                owner="androidx.compose.material.icons.filled.TintKt",
                package="androidx.compose.material.icons.filled",
                disposition="support",
                composable=False,
                declarationKind="property",
                receiver=type_doc("androidx/compose/material/icons/Icons.Filled"),
                returnType=type_doc("kotlin/String"),
            ),
        ],
    )
    spec = propose_icons(
        inventory(tmp_path),
        "androidx/compose/material/icons/Icons",
        {
            "family": "ImageVector",
            "kind": "constant",
            "kotlinType": "androidx.compose.ui.graphics.vector.ImageVector",
        },
        since="1.21.0",
    )
    # The label is where the icon is read from, a deprecated twin is not offered
    # and a same-named property of another type is not an icon.
    assert spec["parameters"]["name"]["values"] == ["Filled.Add", "Outlined.Add"]
    assert spec["family"] == "ImageVector"
    assert spec["kind"] == "constant"
    assert spec["since"] == "1.21.0"
    assert spec["source"] == {
        "owner": "androidx/compose/material/icons/Icons",
        "members": "public properties",
    }
    # An extension property only resolves where it is declared, so the packages
    # come along with the members they declare.
    assert spec["native"] == {
        "constantParameter": "name",
        "propertyOwner": "androidx.compose.material.icons.Icons",
        "imports": [
            "androidx.compose.material.icons.filled",
            "androidx.compose.material.icons.outlined",
        ],
    }


def test_icon_proposal_refuses_a_holder_with_no_icons(tmp_path) -> None:
    from schema.classpath_dump import inventory
    from schema.propose import propose_icons

    write_inventory(tmp_path, [declaration()])
    with pytest.raises(ValueError, match="no public ImageVector members"):
        propose_icons(
            inventory(tmp_path),
            "androidx/compose/material/icons/Icons",
            {
                "family": "ImageVector",
                "kind": "constant",
                "kotlinType": "androidx.compose.ui.graphics.vector.ImageVector",
            },
            since="1.21.0",
        )


def test_pinned_source_defaults_generate_native_factories(native_document) -> None:
    from schema.classpath_dump import inventory, source_defaults
    from schema.propose import propose_value

    assert native_document["provenance"]["bom"] == "2025.01.01"
    found = inventory(DUMP)
    defaults = source_defaults(DUMP)
    source = next(
        d
        for d in found.declarations
        if d.name == "buttonColors" and d.parameters and len(d.parameters) == 4
    )
    spec = propose_value(
        source,
        since="1.11.0",
        families={"androidx.compose.ui.graphics.Color": "Color"},
        defaults=defaults[source.owner, source.jvm_name, source.jvm_descriptor],
    )
    assert list(spec["parameters"]) == [
        "containerColor",
        "contentColor",
        "disabledContainerColor",
        "disabledContentColor",
    ]
    assert spec["parameters"]["containerColor"]["default"] == {
        "kind": "property",
        "symbol": "androidx.compose.ui.graphics.Color.Companion.Unspecified",
    }
    assert "defaultNative" not in json.dumps(spec)


def test_internal_immutable_tokens_reduce_to_public_typed_defaults(
    native_document,
) -> None:
    assert native_document["provenance"]["compiler"] == "2.0.21"
    # Resolve the immutable initializer chain, without referencing internal API
    # or transcribing token values into binding policy.
    resolve = ["--console=plain", "-PcomposeValueNames=buttonElevation"]
    try:
        result = subprocess.run(
            ["./gradlew", "dumpComposeDefaults", *resolve],
            cwd="android",
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert_resolves_token_defaults()
    finally:
        # Restore the catalog-wide evidence the other seams depend on.
        subprocess.run(
            ["./gradlew", "dumpComposeDefaults", "--console=plain"],
            cwd="android",
            capture_output=True,
            text=True,
            check=False,
        )


def assert_resolves_token_defaults() -> None:
    """Pinned immutable elevation tokens reduce to 0/1 dp, not internal symbols."""
    from schema.classpath_dump import inventory, source_defaults
    from schema.propose import propose_value

    found = inventory(DUMP)
    defaults = source_defaults(DUMP)
    source = next(d for d in found.declarations if d.name == "buttonElevation")
    key = (source.owner, source.jvm_name, source.jvm_descriptor)
    spec = propose_value(
        source,
        since="1.11.0",
        families={"androidx.compose.ui.unit.Dp": "Dp"},
        defaults=defaults[key],
    )
    assert "tokens" not in json.dumps(spec["parameters"])
    for name, rule in spec["parameters"].items():
        assert rule["default"] == {
            "kind": "extensionProperty",
            "symbol": "androidx.compose.ui.unit.dp",
            "receiver": {
                "kind": "literal",
                "type": "kotlin/Double",
                "value": 1.0 if name == "hoveredElevation" else 0.0,
            },
        }


@pytest.mark.parametrize(
    ("initializer", "reason"),
    [
        (
            "public fun nextValue(): Int = 1\ninternal val Frozen = nextValue()",
            "call in token initializer",
        ),
        (
            "public val computed: Int get() = 1\ninternal val Frozen = computed",
            "computed reference in token initializer",
        ),
        ("internal val Frozen: Int get() = 1", "computed token default"),
        ("internal var Frozen = 1", "mutable default reference"),
        ("internal val Frozen by lazy { 1 }", "computed token default"),
        (
            "internal val Frozen: Int = Other\ninternal val Other: Int = Frozen",
            "cyclic/deep token default",
        ),
        (
            "internal object Tokens { val Fixed = 1 }\n"
            'internal fun choose(): Tokens = error("must execute")\n'
            "internal val Frozen = choose().Fixed",
            "computed qualifier in default",
        ),
    ],
)
def test_unsafe_token_initializers_are_refused(
    native_document, tmp_path, initializer, reason
) -> None:
    import zipfile

    assert native_document["provenance"]["compiler"] == "2.0.21"
    request_path = ROOT / DUMP / "source-request.json"
    request = json.loads(request_path.read_text())
    tool = ROOT / "android/tools/SourceDefaults.kt"
    assert request["toolHash"] == hashlib.sha256(tool.read_bytes()).hexdigest()
    archive = tmp_path / "probe-sources.jar"
    with zipfile.ZipFile(archive, "w") as source:
        source.writestr(
            "Probe.kt",
            "package probe\n"
            + initializer
            + "\npublic fun target(value: Int = Frozen): Int = value\n",
        )
    integer = type_doc("kotlin/Int")
    request.update(
        sources=[
            {
                "artifact": "fixture:probe:1",
                "file": str(archive),
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            }
        ],
        targets=[
            declaration(
                "target",
                "(I)I",
                artifact="fixture:probe:1",
                owner="probe.ProbeKt",
                package="probe",
                disposition="support",
                composable=False,
                annotations={},
                declarationKind="function",
                sourceFile="Probe.kt",
                returnType=integer,
                parameters=[parameter("value", integer, has_default=True)],
            )
        ],
    )
    probe_request = tmp_path / "request.json"
    probe_result = tmp_path / "result.json"
    probe_request.write_text(json.dumps(request))
    result = subprocess.run(
        [
            request["javaExecutable"],
            "-cp",
            os.pathsep.join(
                [
                    *request["compilerClasspath"],
                    str(request_path.parent / "source-tool"),
                ]
            ),
            "SourceDefaultsKt",
            str(probe_request),
            str(probe_result),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads(probe_result.read_text())["declarations"][0]
    assert record["matched"] is True
    assert record["defaults"]["value"]["kind"] == "unsupported"
    assert reason in record["defaults"]["value"]["reason"]


def test_class_evidence_separates_sibling_vocabularies(native_document) -> None:
    from schema.classpath_dump import inventory, opt_in_markers
    from schema.propose import propose_members

    assert native_document["provenance"]["bom"] == "2025.01.01"
    found = inventory(DUMP)
    vertical = next(
        evidence
        for evidence in found.classes
        if evidence.owner == "androidx.compose.ui.Alignment$Vertical"
    )
    assert vertical.class_kind == "INTERFACE"
    assert vertical.visibility == "PUBLIC"
    # Only recorded class facts decide assignability: a sibling type is not a
    # subtype, however the name reads.
    assert vertical.supertypes == ("kotlin/Any",)
    companion = "androidx/compose/ui/Alignment$Companion"
    markers = opt_in_markers(found)
    alignment = propose_members(
        found,
        companion,
        {
            "family": "Alignment",
            "kotlinType": "androidx.compose.ui.Alignment",
            "kind": "constant",
        },
        since="1.14.0",
        opt_ins=markers,
        also_from=("androidx/compose/ui/AbsoluteAlignment",),
    )
    assert alignment["parameters"]["name"]["values"] == [
        "BottomCenter",
        "BottomEnd",
        "BottomLeft",
        "BottomRight",
        "BottomStart",
        "Center",
        "CenterEnd",
        "CenterLeft",
        "CenterRight",
        "CenterStart",
        "TopCenter",
        "TopEnd",
        "TopLeft",
        "TopRight",
        "TopStart",
    ]
    assert alignment["native"]["propertyOwner"] == "androidx.compose.ui.Alignment"
    assert alignment["native"]["owners"] == {
        "BottomLeft": "androidx.compose.ui.AbsoluteAlignment",
        "BottomRight": "androidx.compose.ui.AbsoluteAlignment",
        "CenterLeft": "androidx.compose.ui.AbsoluteAlignment",
        "CenterRight": "androidx.compose.ui.AbsoluteAlignment",
        "TopLeft": "androidx.compose.ui.AbsoluteAlignment",
        "TopRight": "androidx.compose.ui.AbsoluteAlignment",
    }
    upright = propose_members(
        found,
        companion,
        {
            "family": "AlignmentVertical",
            "kotlinType": "androidx.compose.ui.Alignment.Vertical",
            "kind": "constant",
        },
        since="1.14.0",
        opt_ins=markers,
    )
    assert upright["parameters"]["name"]["values"] == [
        "Bottom",
        "CenterVertically",
        "Top",
    ]
    assert "owners" not in upright["native"]


def test_refresh_rebinds_the_whole_catalog_without_hand_edits(native_document) -> None:
    from schema.check_upstream import compare_values
    from schema.classpath_dump import inventory, source_defaults
    from schema.propose import refresh

    assert native_document["provenance"]["compiler"] == "2.0.21"
    found = inventory(DUMP)
    evidence = source_defaults(DUMP)
    registry = json.loads((ROOT / "schema/components.json").read_text())
    results = refresh(found, evidence, registry)
    derived = [item for item in results if "proposal" in item]
    # Every approved binding carrying a source is re-derived, not silently skipped.
    assert {item["name"] for item in derived} == {
        name
        for name, spec in registry["valueTypes"].items()
        if "family" in spec and "source" in spec
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
    assert specs["datePickerColors"]["optIn"] == [
        "androidx.compose.material3.ExperimentalMaterial3Api"
    ]
    assert "optIn" not in specs["checkboxColors"]
    assert specs["TimePickerLayoutType"]["optIn"] == [
        "androidx.compose.material3.ExperimentalMaterial3Api"
    ]
    assert len(specs["ThemeColor"]["parameters"]["name"]["values"]) == 36
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


def test_opt_in_evidence_comes_from_the_pin(native_document) -> None:
    from schema.classpath_dump import inventory, opt_in_markers, required_opt_ins

    assert native_document["provenance"]["compiler"] == "2.0.21"
    found = inventory(DUMP)
    markers = opt_in_markers(found)
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
    assert required_opt_ins(experimental, markers) == {
        "androidx.compose.material3.ExperimentalMaterial3Api"
    }
    assert required_opt_ins(stable, markers) == set()


def test_release_drift_is_reported_instead_of_silently_accepted(
    native_document,
) -> None:
    from schema.check_upstream import DRIFT, compare_values
    from schema.classpath_dump import inventory, source_defaults

    assert native_document["artifacts"]
    found = inventory(DUMP)
    registry = json.loads((ROOT / "schema/components.json").read_text())
    # A release that changes a default must show up as a proposal diff for a
    # person to review, never be silently adopted.
    registry["valueTypes"]["buttonColors"]["parameters"]["containerColor"]["default"][
        "symbol"
    ] = "androidx.compose.ui.graphics.Color.Companion.Red"
    errors = compare_values(registry, found, source_defaults(DUMP))
    assert errors == [f"buttonColors: {DRIFT}"]


def test_named_member_and_omission_drift_require_review(native_document) -> None:
    from dataclasses import replace

    from schema.check_upstream import DRIFT, compare_values
    from schema.classpath_dump import inventory, source_defaults

    assert native_document["artifacts"]
    registry = json.loads((ROOT / "schema/components.json").read_text())
    registry["valueTypes"]["ThemeColor"]["parameters"]["name"]["values"].remove(
        "primary"
    )
    registry["valueTypes"]["TextStyle"]["omitted"].pop("fontStyle")
    errors = compare_values(registry, inventory(DUMP), source_defaults(DUMP))
    assert set(errors) == {f"ThemeColor: {DRIFT}", f"TextStyle: {DRIFT}"}
    found = inventory(DUMP)
    changed = replace(
        found,
        declarations=tuple(
            replace(d, return_type=replace(d.return_type, nullable=True))
            if d.owner == "androidx.compose.material3.ColorScheme"
            and d.name == "primary"
            else d
            for d in found.declarations
        ),
    )
    errors = compare_values(registry, changed, source_defaults(DUMP))
    assert any("ThemeColor:" in error and "nullable" in error for error in errors)


def test_icon_vocabulary_drift_requires_review(native_document) -> None:
    from schema.check_upstream import DRIFT, compare_values
    from schema.classpath_dump import inventory, source_defaults

    assert native_document["artifacts"]
    registry = json.loads((ROOT / "schema/components.json").read_text())
    icon = registry["valueTypes"]["materialIcon"]
    # A label the pin no longer carries and a package that declares nothing the
    # vocabulary names are both facts of the pin, so an approved copy of either
    # has to surface as a proposal diff for a person to review.
    icon["parameters"]["name"]["values"].remove("Filled.Add")
    icon["native"]["imports"] = ["androidx.compose.material.icons.filled"]
    assert compare_values(registry, inventory(DUMP), source_defaults(DUMP)) == [
        f"materialIcon: {DRIFT}"
    ]


def test_inline_value_overloads_are_not_collapsed_by_jvm_erasure(tmp_path) -> None:
    from schema.classpath_dump import inventory
    from schema.propose import bind

    records = [
        declaration(
            name="RoundedCornerShape",
            descriptor="(F)Landroidx/compose/ui/graphics/Shape;",
            owner="androidx.compose.foundation.shape.RoundedCornerShapeKt",
            package="androidx.compose.foundation.shape",
            disposition="support",
            composable=False,
            declarationKind="function",
            returnType=type_doc("androidx/compose/ui/graphics/Shape"),
            parameters=[parameter("size", type_doc(classifier))],
            jvm={
                "name": jvm,
                "descriptor": "(F)Landroidx/compose/ui/graphics/Shape;",
                "matched": True,
            },
        )
        for classifier, jvm in [
            ("kotlin/Float", "RoundedCornerShape"),
            ("androidx/compose/ui/unit/Dp", "RoundedCornerShape-dp"),
        ]
    ]
    write_inventory(tmp_path, [declaration(), *records])
    found = inventory(tmp_path)
    assert len(found.declarations) == 3
    registry = {
        "schemaVersion": "1.11.0",
        "valueTypes": {
            "Dp": {"family": "Dp", "kotlinType": "androidx.compose.ui.unit.Dp"},
            "RoundedCornerShape": {
                "family": "Shape",
                "kotlinType": "androidx.compose.ui.graphics.Shape",
                "parameters": {
                    "size": {"type": "value", "valueType": "Dp", "required": True}
                },
            },
        },
    }
    result = bind(found, {}, registry, "RoundedCornerShape")
    assert result["proposal"]["source"]["jvmName"] == "RoundedCornerShape-dp"
    assert result["proposal"]["parameters"]["size"]["valueType"] == "Dp"


def test_unused_pinned_constructor_is_generated_decoded_and_renders(
    native_document,
    tmp_path: Path,
) -> None:
    from pycompose.schema.codegen.values import (
        render_models,
        render_native,
        render_python,
    )
    from schema.classpath_dump import inventory
    from schema.propose import propose_value

    assert native_document["bytecodeAudit"]["unmatchedTargetMethods"] == []
    source = next(
        d
        for d in inventory(DUMP).declarations
        if d.owner == "androidx.compose.ui.geometry.Rect" and d.name == "<init>"
    )
    spec = propose_value(source, since="1.11.0", families={})
    # Approval here is test-local: Rect is not added to the shipped catalog.
    registry = {"schemaVersion": "1.12.0", "valueTypes": {"Rect": spec}}
    namespace = {}
    exec(render_python(registry), namespace)
    data = namespace["Rect"](1, 2, 11, 22)
    assert data == {"type": "Rect", "left": 1, "top": 2, "right": 11, "bottom": 22}
    (tmp_path / "ValueModels.kt").write_text(
        render_models(registry).replace(
            "com.pycompose.ir.generated", "com.pycompose.proof"
        )
    )
    (tmp_path / "ValueResolver.kt").write_text(
        render_native(registry)
        .replace("com.pycompose.ir.generated", "com.pycompose.proof")
        .replace("com.pycompose.renderer.generated", "com.pycompose.proof")
    )
    encoded = json.dumps(json.dumps(data))
    (tmp_path / "GeneratedBindingProof.kt").write_text(f"""
package com.pycompose.proof

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertWidthIsEqualTo
import androidx.compose.ui.test.assertHeightIsEqualTo
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.dp
import kotlinx.serialization.json.Json
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class GeneratedBindingProof {{
    @get:Rule val compose = createComposeRule()
    @Test fun unusedConstructorControlsNativeLayout() {{
        compose.setContent {{
            val json = Json.parseToJsonElement({encoded})
            val rect = ValueResolver.rect(json).getOrThrow()
            Box(Modifier.size(rect.width.dp, rect.height.dp).testTag("rect"))
        }}
        compose.onNodeWithTag("rect").assertWidthIsEqualTo(10.dp).assertHeightIsEqualTo(20.dp)
    }}
}}
""")
    init = tmp_path / "proof.gradle"
    init.write_text(
        "gradle.projectsEvaluated { gradle.rootProject.project(':host').android."
        f"sourceSets.test.java.srcDir({json.dumps(str(tmp_path))}) }}"
    )
    result = subprocess.run(
        [
            "./gradlew",
            "-Pkotlin.incremental=false",
            "--init-script",
            str(init),
            ":host:testDebugUnitTest",
            "--tests",
            "com.pycompose.proof.GeneratedBindingProof",
            "--console=plain",
        ],
        cwd="android",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "defect",
    [
        "format",
        "version",
        "default",
        "match",
        "empty",
        "diagnostic",
        "artifact",
        "classes",
        "override",
        "stale",
    ],
)
def test_inventory_refuses_untrusted_or_incomplete_input(
    tmp_path: Path, defect: str
) -> None:
    from schema.classpath_dump import inventory

    document = write_inventory(
        tmp_path,
        [declaration(parameters=[parameter("text", type_doc("kotlin/String"))])],
    )
    if defect == "format":
        document["formatVersion"] = 99
    elif defect == "version":
        document["provenance"]["bom"] = "2099.01.01"
    elif defect == "default":
        document["declarations"][0]["parameters"][0]["hasDefault"] = None
    elif defect == "match":
        document["declarations"][0]["jvm"]["matched"] = False
    elif defect == "empty":
        document["declarations"] = []
    elif defect == "diagnostic":
        document["diagnostics"] = [
            {"target": True, "message": "unread public signature"}
        ]
    elif defect == "artifact":
        document["artifacts"] = []
    elif defect == "classes":
        document["classes"] = []
    elif defect == "stale":
        document["provenance"]["sourceHashes"]["dump-compose-api.gradle.kts"] = "0" * 64
    else:
        coordinate = ARTIFACT.replace("1.3.1", "1.4.0")
        document["artifacts"][0]["coordinate"] = coordinate
        document["declarations"][0]["artifact"] = coordinate
    (tmp_path / "inventory.json").write_text(json.dumps(document))
    with pytest.raises(ValueError):
        inventory(tmp_path)


def test_inventory_preserves_recursive_types_and_distinguishes_builders(
    tmp_path: Path,
) -> None:
    from schema.classpath_dump import inventory

    unit = type_doc("kotlin/Unit")
    extension = ("kotlin/ExtensionFunctionType",)
    nullable = type_doc("kotlin/String") | {"nullable": True}
    mapping = type_doc("kotlin/collections/Map", type_doc("kotlin/Int"), nullable)
    mapping["arguments"][1]["variance"] = "OUT"
    records = [
        declaration(
            parameters=[
                parameter("mapping", mapping),
                parameter(
                    "items",
                    type_doc(
                        "kotlin/Function1",
                        type_doc("androidx/compose/foundation/lazy/LazyListScope"),
                        unit,
                        annotations=extension,
                    ),
                ),
                parameter(
                    "draw",
                    type_doc(
                        "kotlin/Function1",
                        type_doc("androidx/compose/ui/graphics/drawscope/DrawScope"),
                        unit,
                        annotations=extension,
                    ),
                ),
            ]
        )
    ]
    write_inventory(tmp_path, records)
    params = {p.name: p for p in inventory(tmp_path).ui[0].parameters}
    assert len(params["mapping"].type.arguments) == 2
    assert params["mapping"].type.arguments[1][0] == "OUT"
    assert params["mapping"].type.arguments[1][1].nullable is True
    assert params["items"].kind.value == "builder"
    assert params["draw"].kind.value == "unknown"


def test_gap_report_is_a_capability_worklist_not_a_support_claim(
    tmp_path: Path,
) -> None:
    from schema.classpath_dump import inventory

    write_inventory(
        tmp_path,
        [
            declaration(
                parameters=[
                    parameter(
                        "state", type_doc("androidx/compose/material3/SheetState")
                    ),
                    parameter(
                        "onClick", type_doc("kotlin/Function0", type_doc("kotlin/Unit"))
                    ),
                ]
            )
        ],
    )
    report = inventory(tmp_path).capability_report()
    assert report["status"] == "discovery-only"
    assert report["componentNames"] == 1
    assert report["overloads"] == 1
    assert report["families"]["value"] == {"androidx/compose/material3/SheetState": 1}
    assert report["families"]["callback"] == {"kotlin/Function0": 1}
    assert report["controllerCandidates"] == {
        "androidx/compose/material3/SheetState": 1
    }
    assert report["gaps"][0]["parameter"] == "state"
    assert report["gaps"][0]["status"] == "needs-capability-audit"


def test_unread_referenced_support_blocks_the_inventory(tmp_path: Path) -> None:
    from schema.classpath_dump import inventory

    support = declaration(
        name="operation",
        owner="androidx.compose.material3.Controller",
        disposition="error",
        reason="unmatched metadata signature",
        jvm={"name": "operation", "descriptor": "broken", "matched": False},
    )
    component = declaration(
        parameters=[
            parameter("state", type_doc("androidx/compose/material3/Controller")),
        ]
    )
    write_inventory(tmp_path, [component, support])
    with pytest.raises(ValueError, match="required support"):
        inventory(tmp_path)


def test_unmatched_public_accessor_is_not_treated_as_inaccessible(
    tmp_path: Path,
) -> None:
    from schema.classpath_dump import inventory

    public_getter = {
        "name": "getMonth",
        "descriptor": "()J",
        "visibility": "PUBLIC",
        "matched": True,
        "callable": True,
    }
    public_setter = {
        "name": "setMonth",
        "descriptor": "(J)V",
        "visibility": "PUBLIC",
        "matched": False,
        "callable": False,
    }
    write_inventory(
        tmp_path,
        [
            declaration(),
            declaration(
                name="month",
                descriptor="()J",
                disposition="support",
                accessors={"getter": public_getter, "setter": public_setter},
            ),
        ],
    )
    with pytest.raises(ValueError, match="accessor"):
        inventory(tmp_path)


def test_vararg_can_be_omitted_without_a_default_expression(tmp_path: Path) -> None:
    from schema.classpath_dump import inventory

    string = type_doc("kotlin/String")
    locales = parameter("locales", type_doc("kotlin/Array", string)) | {
        "varargType": string
    }
    write_inventory(tmp_path, [declaration(parameters=[locales])])
    argument = inventory(tmp_path).ui[0].parameters[0]
    assert argument.has_default is False
    assert argument.required is False
