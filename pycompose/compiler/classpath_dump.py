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
import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pycompose.compiler.classpath_types import (  # noqa: F401 -- typed view re-exports
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
    "OptInIndex",
    "Parameter",
    "SOURCE_PATTERNS",
    "opt_in_index",
    "opt_in_markers",
    "required_opt_ins",
    "source_defaults",
    "summarise",
    "inventory",
]


SOURCE_PATTERNS = (
    "*.gradle.kts",
    "*/build.gradle.kts",
    "compose-extract/src/main/kotlin/*.kt",
    "gradle/libs.versions.toml",
    "gradle.properties",
)
"""Files under android/ whose bytes the inventory was extracted with.

``dumpComposeApi`` hashes the same set (compose-extract/build.gradle.kts); a
change to any of them makes the evidence stale.
"""


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


def _signature_types(declaration: Declaration) -> Iterator[KotlinType]:
    """Yield every type reachable from one declaration's signature.

    Parameters, receivers and the return type are walked, then generic
    arguments and aliases of each, because an experimental type nested in a
    signature still gates the call site.
    """
    pending = [declaration.return_type]
    for parameter in declaration.parameters:
        pending.append(parameter.type)
        if parameter.vararg_type is not None:
            pending.append(parameter.vararg_type)
    pending.extend(
        receiver
        for receiver in (
            declaration.receiver,
            declaration.dispatch_receiver,
            *declaration.context_receivers,
        )
        if receiver is not None
    )
    seen: set[int] = set()
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        yield value
        for _, argument in value.arguments:
            if argument is not None:
                pending.append(argument)
        pending.extend(
            nested
            for nested in (
                value.abbreviated_type,
                value.outer_type,
                value.flexible_upper_bound,
            )
            if nested is not None
        )


@dataclass(frozen=True)
class OptInIndex:
    """The pin's opt-in markers and the classes that carry one.

    A call site needs opt-in when the declaration is annotated with a marker
    *or* when a type in its signature is: the compiler flags both, and the
    M3 1.4.0 app-bar overloads proved the second half is real (their
    ``scrollBehavior`` parameter type is ``@ExperimentalMaterial3Api`` while
    the functions themselves are unannotated).

    ``inaccessible`` lists markers declared non-public: callers outside the
    library cannot name them in ``@OptIn``, so a declaration gated by one is
    not renderable and must fail closed instead of emitting uncompilable code.
    """

    markers: frozenset[str] = frozenset()
    types: Mapping[str, frozenset[str]] = field(default_factory=dict)
    inaccessible: frozenset[str] = frozenset()

    def of(self, declaration: Declaration) -> set[str]:
        """Report the markers a native call to one declaration must opt in to.

        Args:
            declaration: One pinned declaration.

        Returns:
            The dotted markers a native call site must opt in to.
        """
        markers = {name.replace("/", ".") for name in declaration.annotations}
        required = {name for name in markers if name in self.markers}
        for value in _signature_types(declaration):
            required |= self.types.get(value.classifier.replace("/", "."), frozenset())
        return required


def opt_in_index(found: Inventory) -> OptInIndex:
    """Build the pin's opt-in index, markers plus every carrying type.

    Args:
        found: The validated inventory of the current pin.

    Returns:
        The index a proposal or native call renders its ``@OptIn`` from.
    """
    markers = opt_in_markers(found)
    classes = {klass.owner: klass for klass in found.classes}
    carried: dict[str, frozenset[str]] = {}

    def of_type(owner: str, seen: frozenset[str]) -> frozenset[str]:
        cached = carried.get(owner)
        if cached is not None:
            return cached
        if owner in seen:
            return frozenset()
        klass = classes.get(owner)
        if klass is None:
            return frozenset()
        marks = {
            name.replace("/", ".")
            for name in klass.document["annotations"]
            if name.replace("/", ".") in markers
        }
        for supertype in klass.supertypes:
            marks |= of_type(supertype.replace("/", "."), seen | {owner})
        carried[owner] = frozenset(marks)
        return carried[owner]

    for klass in found.classes:
        of_type(klass.owner, frozenset())
    visibility = {klass.owner: klass.visibility for klass in found.classes}
    inaccessible = frozenset(
        marker for marker in markers if visibility.get(marker) not in (None, "PUBLIC")
    )
    return OptInIndex(
        markers=frozenset(markers), types=carried, inaccessible=inaccessible
    )


def required_opt_ins(declaration: Declaration, index: OptInIndex) -> set[str]:
    """Report which of a declaration's evidence needs an opt-in.

    Args:
        declaration: One pinned declaration.
        index: The pin's opt-in index.

    Returns:
        The dotted markers a native call site must opt in to.
    """
    return index.of(declaration)


UNRESOLVED = {"kind": "unsupported", "reason": "source could not be pinned"}
"""Reported per binding, so one ambiguous declaration never blinds the catalog."""


def _tool_digest() -> str:
    """Digest every tool source in file-name order: both halves own the contract."""
    digest = hashlib.sha256()
    android = Path(__file__).resolve().parents[2] / "android"
    tools = android / "compose-extract/src/main/kotlin"
    for tool in sorted(tools.glob("*.kt")):
        digest.update(tool.read_bytes())
    return digest.hexdigest()


def source_defaults(
    directory: Path = DUMP_DIR,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Read compiler-resolved defaults only while artifacts/tool inputs still match."""
    result = {}
    for key, declaration in _source_evidence(directory).items():
        if not declaration["matched"]:
            # One binding the sources could not pin must not blind the others;
            # the proposal for it simply loses its defaults and shows as drift.
            result[key] = {p: UNRESOLVED for p in declaration["defaults"]}
            continue
        result[key] = declaration["defaults"]
    return result


def source_drives(
    directory: Path = DUMP_DIR,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Read the anchor each holder suspend member drives to, from the same evidence."""
    return {
        key: declaration["drive"]
        for key, declaration in _source_evidence(directory).items()
        if "drive" in declaration
    }


def _source_evidence(directory: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Validated source evidence keyed by JVM identity."""
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
        result[key] = declaration
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
        for pattern in SOURCE_PATTERNS
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
    _require(any(d["disposition"] == "ui" for d in records), "no public components")
    groups = json.loads((android / "compose-closure.json").read_text(encoding="utf-8"))
    components = {
        name for name, group in groups["groups"].items() if group.get("components")
    }
    identities: set[tuple[str, str, str | None, str | None]] = set()
    for record in records:
        _require(
            record["artifact"] in artifacts, "declaration has no resolved artifact"
        )
        if record["disposition"] == "ui":
            _require(
                record["artifact"] in android_artifacts,
                "a component requires an Android variant",
            )
            _require(
                record["artifact"].split(":")[0] in components,
                "component from a group the closure does not mark as components",
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
    if "inline" in record:
        _require(type(record["inline"]) is bool, "unknown inline semantics")
    if disposition == "ui":
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
    """Report public component overloads separately from support and exclusions."""
    found = inventory(directory)
    return (
        f"BOM {found.bom}, Kotlin/Compose compiler {found.compiler}\n"
        f"{len({d.name for d in found.ui})} public component names, "
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
