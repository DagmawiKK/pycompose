"""Value, member, icon and token proposals the classpath pin supports."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess

import pytest
from test_classpath_dump import (
    DUMP,
    ROOT,
    declaration,
    parameter,
    type_doc,
    write_inventory,
)


def test_value_proposal_derives_an_unused_constructor_without_parameter_policy() -> (
    None
):
    from tools.schema.classpath_dump import Declaration
    from tools.schema.propose import propose_value

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
    from tools.schema.classpath_dump import Declaration
    from tools.schema.propose import propose_value

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
    from tools.schema.classpath_dump import inventory
    from tools.schema.propose import propose_members

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
    from tools.schema.classpath_dump import inventory
    from tools.schema.propose import propose_icons

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
    from tools.schema.classpath_dump import inventory
    from tools.schema.propose import propose_icons

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
    from tools.schema.classpath_dump import inventory, source_defaults
    from tools.schema.propose import propose_value

    assert native_document["provenance"]["bom"] == "2026.09.00"
    found = inventory(DUMP)
    defaults = source_defaults(DUMP)
    source = next(
        d
        for d in found.declarations
        if d.owner == "androidx.compose.material3.ButtonDefaults"
        and d.name == "buttonColors"
        and d.parameters
        and len(d.parameters) == 4
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
    assert native_document["provenance"]["compiler"] == "2.4.21"
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
    from tools.schema.classpath_dump import inventory, source_defaults
    from tools.schema.propose import propose_value

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

    assert native_document["provenance"]["compiler"] == "2.4.21"
    request_path = ROOT / DUMP / "source-request.json"
    request = json.loads(request_path.read_text())
    tool = ROOT / "android/compose-extract/src/main/kotlin"
    digest = hashlib.sha256()
    for half in sorted(tool.glob("*.kt")):
        digest.update(half.read_bytes())
    assert request["toolHash"] == digest.hexdigest()
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
            os.pathsep.join(request["compilerClasspath"]),
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
    from tools.schema.classpath_dump import inventory, opt_in_index
    from tools.schema.propose import propose_members

    assert native_document["provenance"]["bom"] == "2026.09.00"
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
    index = opt_in_index(found)
    alignment = propose_members(
        found,
        companion,
        {
            "family": "Alignment",
            "kotlinType": "androidx.compose.ui.Alignment",
            "kind": "constant",
        },
        since="1.14.0",
        opt_ins=index,
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
        opt_ins=index,
    )
    assert upright["parameters"]["name"]["values"] == [
        "Bottom",
        "CenterVertically",
        "Top",
    ]
    assert "owners" not in upright["native"]
