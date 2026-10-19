"""Behavioral tests at the artifact extraction and public inventory seams."""

from __future__ import annotations

import hashlib
import json
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
            "compiler": "2.4.21",
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
    from tools.schema.classpath_dump import inventory

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
    from tools.schema.classpath_dump import inventory

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
    from tools.schema.classpath_dump import inventory

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
    from tools.schema.classpath_dump import inventory

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
    from tools.schema.classpath_dump import inventory

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
    from tools.schema.classpath_dump import inventory

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
    from tools.schema.classpath_dump import inventory

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
    from tools.schema.classpath_dump import inventory

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
    from tools.schema.classpath_dump import inventory

    string = type_doc("kotlin/String")
    locales = parameter("locales", type_doc("kotlin/Array", string)) | {
        "varargType": string
    }
    write_inventory(tmp_path, [declaration(parameters=[locales])])
    argument = inventory(tmp_path).ui[0].parameters[0]
    assert argument.has_default is False
    assert argument.required is False
