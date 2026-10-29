"""Compiler identity checks for native APIs with value-class parameters."""

from __future__ import annotations

import json
import os
import re
import subprocess
import zipfile
from pathlib import Path

from test_classpath_dump import DUMP


def test_measure_policy_identity_matches_the_kotlin_compiler(
    native_document, tmp_path: Path
) -> None:
    measure = next(
        declaration
        for declaration in native_document["declarations"]
        if declaration["owner"] == "androidx.compose.ui.layout.MeasurePolicy"
        and declaration["name"] == "measure"
    )
    assert measure["disposition"] == "support", measure["reason"]
    assert measure["jvm"]["matched"] is True
    # Keep Kotlin's source type, not just the ABI's unboxed long.
    assert measure["parameters"][-1]["type"]["classifier"] == (
        "androidx/compose/ui/unit/Constraints"
    )
    source = tmp_path / "LayoutIdentity.kt"
    source.write_text("""
import androidx.compose.ui.layout.Measurable
import androidx.compose.ui.layout.MeasurePolicy
import androidx.compose.ui.layout.MeasureScope
import androidx.compose.ui.unit.Constraints

fun measure(policy: MeasurePolicy, scope: MeasureScope,
            children: List<Measurable>, constraints: Constraints) =
    with(policy) { scope.measure(children, constraints) }
""")
    request = json.loads((DUMP / "source-request.json").read_text())
    classes = tmp_path / "classes"
    result = subprocess.run(
        [
            request["javaExecutable"],
            "-cp",
            os.pathsep.join(request["compilerClasspath"]),
            "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
            "-no-stdlib",
            "-no-reflect",
            "-classpath",
            os.pathsep.join(request["classpath"]),
            "-d",
            str(classes),
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    bytecode = subprocess.run(
        ["javap", "-c", str(classes / "LayoutIdentityKt.class")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    invocations = {
        (name.replace('"', ""), descriptor)
        for name, descriptor in re.findall(r"// InterfaceMethod (\S+):(\S+)", bytecode)
    }
    identity = measure["jvm"]
    assert (
        "androidx/compose/ui/layout/MeasurePolicy." + identity["name"],
        identity["descriptor"],
    ) in invocations


def test_class_literals_in_native_annotations_are_serializable(
    native_document, tmp_path: Path
) -> None:
    source = tmp_path / "AnnotatedApi.kt"
    source.write_text("""
package androidx.compose.fixture
import kotlin.reflect.KClass

@Target(AnnotationTarget.CLASS, AnnotationTarget.FUNCTION)
annotation class ClassReferences(val single: KClass<*>, val many: Array<KClass<*>>)

@ClassReferences(String::class, [Int::class, Array<String>::class])
class AnnotatedApi {
    @ClassReferences(List::class, [Long::class])
    fun work() = Unit
}

@JvmInline value class First(val value: Long)
@JvmInline value class Second(val value: Long)

interface Overloads {
    fun measure(value: First): Long
    fun measure(value: Second): Long
}
""")
    request = json.loads((DUMP / "source-request.json").read_text())
    classes = tmp_path / "classes"
    compiled = subprocess.run(
        [
            request["javaExecutable"],
            "-cp",
            os.pathsep.join(request["compilerClasspath"]),
            "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
            "-no-stdlib",
            "-no-reflect",
            "-classpath",
            os.pathsep.join(request["classpath"]),
            "-d",
            str(classes),
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    repository = tmp_path / "maven"
    artifact = repository / "androidx/compose/fixture/annotation-fixture/1"
    artifact.mkdir(parents=True)
    with zipfile.ZipFile(artifact / "annotation-fixture-1.jar", "w") as archive:
        for path in sorted(classes.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(classes).as_posix())
    (artifact / "annotation-fixture-1.pom").write_text("""
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion><groupId>androidx.compose.fixture</groupId>
  <artifactId>annotation-fixture</artifactId><version>1</version>
</project>
""")
    init = tmp_path / "annotations.gradle"
    init.write_text(
        "gradle.settingsEvaluated { settings -> "
        "settings.dependencyResolutionManagement.repositories.maven { "
        f"url = uri({json.dumps(repository.as_uri())}) "
        "} }; gradle.projectsEvaluated { "
        "gradle.rootProject.project(':renderer').dependencies.add("
        "'debugImplementation', 'androidx.compose.fixture:annotation-fixture:1') }"
    )
    try:
        extracted = subprocess.run(
            [
                "./gradlew",
                "--init-script",
                str(init),
                "dumpComposeApi",
                "--console=plain",
            ],
            cwd="android",
            capture_output=True,
            text=True,
            check=False,
        )
        assert extracted.returncode == 0, extracted.stdout + extracted.stderr
        document = json.loads((DUMP / "inventory.json").read_text())
        annotated = next(
            c
            for c in document["classes"]
            if c["owner"] == "androidx.compose.fixture.AnnotatedApi"
        )
        assert annotated["annotations"]["androidx/compose/fixture/ClassReferences"] == {
            "single": {"classDescriptor": "Ljava/lang/String;"},
            "many": [
                {"classDescriptor": "I"},
                {"classDescriptor": "[Ljava/lang/String;"},
            ],
        }
        work = next(
            d
            for d in document["declarations"]
            if d["owner"] == "androidx.compose.fixture.AnnotatedApi"
            and d["name"] == "work"
        )
        assert work["annotations"]["androidx/compose/fixture/ClassReferences"] == {
            "single": {"classDescriptor": "Ljava/util/List;"},
            "many": [{"classDescriptor": "J"}],
        }
        # Same source name and unboxed ABI do not identify an overload. Keep
        # each compiler-recorded mangled name rather than guessing a sibling.
        overloads = [
            d
            for d in document["declarations"]
            if d["owner"] == "androidx.compose.fixture.Overloads"
            and d["name"] == "measure"
        ]
        assert len(overloads) == 2
        assert len({d["jvm"]["name"] for d in overloads}) == 2
        assert all(d["jvm"]["matched"] for d in overloads)
        assert {d["parameters"][0]["type"]["classifier"] for d in overloads} == {
            "androidx/compose/fixture/First",
            "androidx/compose/fixture/Second",
        }
    finally:
        restored = subprocess.run(
            ["./gradlew", "dumpComposeApi", "--console=plain"],
            cwd="android",
            capture_output=True,
            text=True,
            check=False,
        )
        assert restored.returncode == 0, restored.stdout + restored.stderr
        assert json.loads((DUMP / "inventory.json").read_text()) == native_document
