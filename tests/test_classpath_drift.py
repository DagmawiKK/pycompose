"""Release drift and refused edge cases around the pinned inventory."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from test_classpath_dump import (
    DUMP,
    ROOT,
    declaration,
    parameter,
    type_doc,
    write_inventory,
)


def test_release_drift_is_reported_instead_of_silently_accepted(
    native_document,
) -> None:
    from tools.schema.check_upstream import DRIFT, compare_values
    from tools.schema.classpath_dump import inventory, source_defaults

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

    from tools.schema.check_upstream import DRIFT, compare_values
    from tools.schema.classpath_dump import inventory, source_defaults

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
    from tools.schema.check_upstream import DRIFT, compare_values
    from tools.schema.classpath_dump import inventory, source_defaults

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
    from tools.schema.classpath_dump import inventory
    from tools.schema.propose import bind

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
    from pycompose.schema.codegen.values import render_python
    from pycompose.schema.codegen.values_kotlin import (
        render_models,
        render_native,
    )
    from tools.schema.classpath_dump import inventory
    from tools.schema.propose import propose_value

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
        f"sourceSets.test.kotlin.srcDir({json.dumps(str(tmp_path))}) }}"
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
