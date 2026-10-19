"""Read the resolved Android inventory without erasing overloads or Kotlin types.

Run ``./gradlew dumpComposeApi`` in android/, then this module from the repo root.
The inventory is build output, not the approved component registry. Type discovery
does not imply that a wire encoding or native adapter has been implemented.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # pragma: no cover - only when run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.schema.classpath_types import (  # noqa: F401 -- typed view re-exports
    BUILDERS,
    COMPOSABLE,
    DUMP_DIR,
    EXTENSION,
    Declaration,
    Inventory,
    Kind,
    KotlinClass,
    KotlinType,
    Parameter,
    _type,
)

__all__ = [
    "BUILDERS",
    "COMPOSABLE",
    "DUMP_DIR",
    "Declaration",
    "EXTENSION",
    "Inventory",
    "Kind",
    "KotlinClass",
    "KotlinType",
    "Parameter",
    "opt_in_markers",
    "required_opt_ins",
    "source_defaults",
    "summarise",
    "inventory",
]


def inventory(directory: Path = DUMP_DIR) -> Inventory:
    """Load the single authoritative structured inventory."""
    source = directory / "inventory.json"
    if not source.is_file():
        raise FileNotFoundError(f"{source} is missing; run ./gradlew dumpComposeApi")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        _validate_inventory(data)
        declarations = tuple(Declaration.read(d) for d in data["declarations"])
        found = Inventory(
            bom=data["provenance"]["bom"],
            compiler=data["provenance"]["compiler"],
            declarations=declarations,
            classes=tuple(KotlinClass.read(c) for c in data["classes"]),
            document=data,
        )
        _require(
            not any(d.disposition == "error" for d in found.required_support),
            "unread required support signatures",
        )
        return found
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"incomplete Compose inventory: {exc}") from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def opt_in_markers(found: Inventory) -> set[str]:
    """Report every opt-in annotation the pin itself declares.

    The set is derived from the artifact, never listed by hand: an annotation
    class only counts when the pinned compiler says it is annotated with
    ``kotlin.RequiresOptIn``.

    Args:
        found: The validated inventory of the current pin.

    Returns:
        The fully qualified, dotted annotation classes the pin declares.
    """
    return {
        declaration.owner
        for declaration in found.declarations
        if declaration.document.get("classKind") == "ANNOTATION_CLASS"
        and "kotlin/RequiresOptIn" in declaration.annotations
    }


def required_opt_ins(declaration: Declaration, markers: set[str]) -> set[str]:
    """Report which of a declaration's annotations are opt-in markers.

    Annotation evidence is slash-separated (``androidx/compose/...``) while the
    schema records Kotlin symbols with dots, so the comparison normalizes once
    here instead of at every call site.

    Args:
        declaration: One pinned declaration.
        markers: The pin's opt-in annotation classes, dotted.

    Returns:
        The dotted markers a native call site must opt in to.
    """
    return {
        name.replace("/", ".")
        for name in declaration.annotations
        if name.replace("/", ".") in markers
    }


UNRESOLVED = {"kind": "unsupported", "reason": "source could not be pinned"}
"""Reported per binding, so one ambiguous declaration never blinds the catalog."""


def _tool_digest() -> str:
    """Digest every tool source in file-name order: both halves own the contract."""
    digest = hashlib.sha256()
    tools = Path(__file__).resolve().parents[2] / "android/tools"
    for tool in sorted(tools.glob("*.kt")):
        digest.update(tool.read_bytes())
    return digest.hexdigest()


def source_defaults(
    directory: Path = DUMP_DIR,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Read compiler-resolved defaults only while artifacts/tool inputs still match."""
    found = inventory(directory)
    data = json.loads((directory / "defaults.json").read_text(encoding="utf-8"))
    _require(data["formatVersion"] == 1, "unsupported source evidence format")
    _require(
        data["inventoryHash"]
        == hashlib.sha256((directory / "inventory.json").read_bytes()).hexdigest(),
        "stale source evidence; rerun dumpComposeDefaults",
    )
    _require(
        data["toolHash"] == _tool_digest(),
        "stale source compiler; rerun dumpComposeDefaults",
    )
    artifacts = {item["coordinate"] for item in found.document["artifacts"]}
    for source in data["sources"]:
        _require(
            source["artifact"] in artifacts,
            "source artifact is not on the pinned classpath",
        )
        _require(
            source["sha256"]
            == hashlib.sha256(Path(source["file"]).read_bytes()).hexdigest(),
            "source archive changed; rerun dumpComposeDefaults",
        )
    result = {}
    for declaration in data["declarations"]:
        jvm = declaration["jvm"]
        key = (declaration["owner"], jvm["name"], jvm["descriptor"])
        _require(key not in result, "ambiguous source evidence")
        if not declaration["matched"]:
            # One binding the sources could not pin must not blind the others;
            # the proposal for it simply loses its defaults and shows as drift.
            result[key] = {p: UNRESOLVED for p in declaration["defaults"]}
            continue
        result[key] = declaration["defaults"]
    return result


def _validate_inventory(data: dict[str, Any]) -> None:
    versions = tomllib.loads(
        (
            Path(__file__).resolve().parents[2] / "android/gradle/libs.versions.toml"
        ).read_text(encoding="utf-8")
    )["versions"]
    _require(data["formatVersion"] == 1, "unsupported Compose inventory format")
    provenance = data["provenance"]
    android = Path(__file__).resolve().parents[2] / "android"
    sources = {
        p.relative_to(android).as_posix(): p
        for pattern in (
            "*.gradle.kts",
            "*/build.gradle.kts",
            "gradle/libs.versions.toml",
            "gradle.properties",
        )
        for p in android.glob(pattern)
    }
    _require(
        set(provenance["sourceHashes"]) == set(sources), "stale extraction input set"
    )
    for name, source in sources.items():
        _require(
            provenance["sourceHashes"][name]
            == hashlib.sha256(source.read_bytes()).hexdigest(),
            f"stale extraction input: {name}; rerun dumpComposeApi",
        )
    _require(
        provenance["bom"] == versions["compose-bom"],
        "inventory BOM differs from shipped pin",
    )
    _require(
        provenance["compiler"] == versions["kotlin"],
        "inventory compiler differs from shipped pin",
    )
    _require(
        provenance["configuration"] == ":renderer:debugCompileClasspath",
        "wrong Android classpath",
    )
    artifacts = {a["coordinate"]: a for a in data["artifacts"]}
    _require(not provenance["overrides"], "inventory contains unapproved BOM overrides")
    _require(bool(provenance["bomConstraints"]), "missing resolved BOM constraints")
    _require(bool(artifacts), "inventory has no resolved artifacts")
    _require(len(artifacts) == len(data["artifacts"]), "duplicate resolved artifact")
    android_artifacts: set[str] = set()
    for artifact in artifacts.values():
        module, version = artifact["coordinate"].rsplit(":", 1)
        expected = provenance["bomConstraints"].get(module)
        if expected is not None:
            _require(
                version == expected, "resolved artifact differs from BOM constraint"
            )
        attributes = artifact.get("attributes", {})
        android_aar = (
            artifact["variant"] == "jvm"
            and attributes.get("org.jetbrains.kotlin.platform.type") == "jvm"
            and attributes.get("org.gradle.jvm.environment") == "android"
            and attributes.get("artifactType") == "aar"
            and attributes.get("org.gradle.libraryelements") == "aar"
        )
        _require(
            artifact["variant"] in {"androidJvm", None} or android_aar,
            "non-Android artifact",
        )
        if artifact["variant"] == "androidJvm" or android_aar:
            android_artifacts.add(artifact["coordinate"])
        _require(
            re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]) is not None,
            "invalid artifact hash",
        )
    _require(
        not any(d["target"] for d in data["diagnostics"]),
        "unresolved target extraction errors",
    )
    records = data["declarations"]
    _require(
        any(d["disposition"] == "ui" for d in records), "empty public M3 inventory"
    )
    identities: set[tuple[str, str, str | None, str | None]] = set()
    for record in records:
        _require(
            record["artifact"] in artifacts, "declaration has no resolved artifact"
        )
        if record["disposition"] == "ui":
            _require(
                record["artifact"] in android_artifacts,
                "M3 UI requires an Android variant",
            )
        _validate_declaration(record)
        identity = (
            record["artifact"],
            record["owner"],
            record["jvm"]["name"],
            record["jvm"]["descriptor"],
        )
        _require(identity not in identities, "duplicate JVM declaration")
        identities.add(identity)
    classes = data["classes"]
    _require(bool(classes), "inventory has no class evidence")
    owners: set[str] = set()
    for record in classes:
        _require(record["artifact"] in artifacts, "class has no resolved artifact")
        _require(record["owner"] not in owners, "duplicate class evidence")
        owners.add(record["owner"])
        _require(bool(record["classifier"]), "class evidence has no classifier")
        _require(record["classVisibility"].isupper(), "class visibility is not a token")
        for node in record["classSupertypes"]:
            _validate_type(node)


def _validate_declaration(record: dict[str, Any]) -> None:
    disposition = record["disposition"]
    _require(
        disposition in {"ui", "support", "excluded", "error"},
        "unknown declaration disposition",
    )
    if disposition in {"ui", "support"}:
        _require(
            record["visibility"] == record["classVisibility"] == "PUBLIC",
            "non-public exported declaration",
        )
        _require(record["jvm"]["matched"] is True, "unmatched exported JVM signature")
        _require(
            record["reason"] is None, "exported declaration has an exclusion reason"
        )
        for accessor in record.get("accessors", {}).values():
            if accessor is not None and accessor["visibility"] == "PUBLIC":
                _require(
                    accessor["matched"] is True, "unmatched public property accessor"
                )
    if disposition == "ui":
        _require(
            record["package"].startswith("androidx.compose.material3"),
            "non-M3 component in denominator",
        )
        _require(record["composable"] is True, "non-composable UI declaration")
        _require(
            record["returnType"]["classifier"] == "kotlin/Unit",
            "factory counted as a component",
        )
    for parameter in record["parameters"]:
        _require(
            type(parameter["hasDefault"]) is bool, "unknown parameter default presence"
        )
        _validate_type(parameter["type"])
        if parameter["varargType"] is not None:
            _validate_type(parameter["varargType"])
    for value in (
        record["returnType"],
        record["receiver"],
        record["dispatchReceiver"],
        *record["contextReceivers"],
    ):
        if value is not None:
            _validate_type(value)


def _validate_type(value: dict[str, Any]) -> None:
    _require(
        isinstance(value["classifier"], str)
        and bool(value["classifier"])
        and not value["classifier"].startswith("?"),
        "unread Kotlin classifier",
    )
    _require(type(value["nullable"]) is bool, "unknown Kotlin nullability")
    _require(type(value["suspend"]) is bool, "unknown Kotlin suspend semantics")
    for argument in value["arguments"]:
        _require(
            argument["variance"] in {None, "IN", "OUT", "INVARIANT"},
            "invalid type projection",
        )
        if argument["type"] is not None:
            _validate_type(argument["type"])
    for key in ("abbreviatedType", "outerType", "flexibleUpperBound"):
        if value.get(key) is not None:
            _validate_type(value[key])


def summarise(directory: Path = DUMP_DIR) -> str:
    """Report actual public M3 overloads separately from support and exclusions."""
    found = inventory(directory)
    return (
        f"BOM {found.bom}, Kotlin/Compose compiler {found.compiler}\n"
        f"{len({d.name for d in found.ui})} public M3 component names, "
        f"{len(found.ui)} overloads\n"
        f"{len(found.declarations)} total declarations; "
        "discovery is not adapter coverage"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DUMP_DIR)
    parser.add_argument("--report", type=Path, help="write the capability worklist")
    args = parser.parse_args()
    try:
        print(summarise(args.directory))
        if args.report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(inventory(args.directory).capability_report(), indent=2)
                + "\n",
                encoding="utf-8",
            )
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"classpath_dump.py: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
