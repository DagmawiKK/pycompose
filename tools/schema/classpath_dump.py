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
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

DUMP_DIR = Path("android/build/compose-api")
COMPOSABLE = "androidx/compose/runtime/Composable"
EXTENSION = "kotlin/ExtensionFunctionType"
BUILDERS = {
    "androidx/compose/foundation/lazy/LazyListScope",
    "androidx/compose/foundation/lazy/grid/LazyGridScope",
    "androidx/compose/foundation/lazy/staggeredgrid/LazyStaggeredGridScope",
}


class Kind(Enum):
    """Distinct native semantics; only event callbacks use action dispatch."""

    VALUE = "value"
    CALLBACK = "callback"
    SLOT = "slot"
    PROVIDER = "provider"
    BUILDER = "builder"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class KotlinType:
    """Qualified recursive source type, including all generic projections."""

    classifier: str
    nullable: bool
    annotations: tuple[str, ...]
    arguments: tuple[tuple[str | None, KotlinType | None], ...]
    abbreviated_type: KotlinType | None = None
    outer_type: KotlinType | None = None
    flexible_upper_bound: KotlinType | None = None
    suspend: bool = False
    document: dict[str, Any] | None = None

    @classmethod
    def read(cls, data: dict[str, Any]) -> KotlinType:
        """Read a structured metadata type, not a rendered signature."""
        return cls(
            classifier=data["classifier"],
            nullable=data["nullable"],
            annotations=tuple(data["annotations"]),
            arguments=tuple(
                (a["variance"], cls.read(a["type"]) if a["type"] is not None else None)
                for a in data["arguments"]
            ),
            abbreviated_type=_type(data.get("abbreviatedType")),
            outer_type=_type(data.get("outerType")),
            flexible_upper_bound=_type(data.get("flexibleUpperBound")),
            suspend=data["suspend"],
            document=data,
        )

    @property
    def kind(self) -> Kind:
        """Classify using composable/extension annotations and return types."""
        if not self.classifier.startswith(
            ("kotlin/Function", "kotlin/coroutines/SuspendFunction")
        ):
            return Kind.VALUE
        if COMPOSABLE in self.annotations:
            return Kind.SLOT
        if self.suspend or not self.arguments or self.arguments[-1][1] is None:
            return Kind.UNKNOWN
        returns = self.arguments[-1][1]
        if returns.classifier != "kotlin/Unit":
            # Only no-input value suppliers have a general provider policy.
            # Confirmation/draw/layout lambdas require an explicit protocol.
            return Kind.PROVIDER if len(self.arguments) == 1 else Kind.UNKNOWN
        if EXTENSION in self.annotations:
            receiver = self.arguments[0][1]
            return (
                Kind.BUILDER
                if receiver is not None and receiver.classifier in BUILDERS
                else Kind.UNKNOWN
            )
        return Kind.CALLBACK


def _type(data: dict[str, Any] | None) -> KotlinType | None:
    return KotlinType.read(data) if data is not None else None


@dataclass(frozen=True)
class Parameter:
    """A source value parameter, never a receiver or Compose synthetic argument."""

    name: str
    type: KotlinType
    has_default: bool
    vararg_type: KotlinType | None

    @property
    def required(self) -> bool:
        return not self.has_default and self.vararg_type is None

    @property
    def kind(self) -> Kind:
        return self.type.kind


@dataclass(frozen=True)
class Declaration:
    """One exact JVM-backed Kotlin declaration; overloads are never collapsed."""

    artifact: str
    owner: str
    package: str
    name: str
    disposition: str
    reason: str | None
    composable: bool
    annotations: dict[str, Any]
    receiver: KotlinType | None
    dispatch_receiver: KotlinType | None
    context_receivers: tuple[KotlinType, ...]
    return_type: KotlinType
    parameters: tuple[Parameter, ...]
    jvm_name: str | None
    jvm_descriptor: str | None
    document: dict[str, Any]

    @classmethod
    def read(cls, data: dict[str, Any]) -> Declaration:
        return cls(
            artifact=data["artifact"],
            owner=data["owner"],
            package=data["package"],
            name=data["name"],
            disposition=data["disposition"],
            reason=data["reason"],
            composable=data["composable"],
            annotations=data["annotations"],
            receiver=_type(data["receiver"]),
            dispatch_receiver=_type(data["dispatchReceiver"]),
            context_receivers=tuple(
                KotlinType.read(t) for t in data["contextReceivers"]
            ),
            return_type=KotlinType.read(data["returnType"]),
            parameters=tuple(
                Parameter(
                    p["name"],
                    KotlinType.read(p["type"]),
                    p["hasDefault"],
                    _type(p["varargType"]),
                )
                for p in data["parameters"]
            ),
            jvm_name=data["jvm"]["name"],
            jvm_descriptor=data["jvm"]["descriptor"],
            document=data,
        )


@dataclass(frozen=True)
class Inventory:
    """Artifact provenance and declarations, before any catalog approval."""

    bom: str
    compiler: str
    declarations: tuple[Declaration, ...]
    document: dict[str, Any]

    @property
    def ui(self) -> tuple[Declaration, ...]:
        return tuple(d for d in self.declarations if d.disposition == "ui")

    @property
    def required_support(self) -> tuple[Declaration, ...]:
        """Transitive member signatures of classes referenced by public M3 UI.

        This identifies unread support signatures, not app-generation dependency
        closure: native factory/default implementations need their own audit.
        """
        owners: dict[str, list[Declaration]] = defaultdict(list)
        for declaration in self.declarations:
            owners[declaration.owner.replace("$", ".")].append(declaration)
        required: dict[tuple[str, str | None, str | None], Declaration] = {}
        pending = list(self.ui)
        visited: set[str] = set()
        while pending:
            declaration = pending.pop()
            for classifier in _classifiers(declaration.document):
                owner = classifier.replace("/", ".")
                if owner in visited:
                    continue
                visited.add(owner)
                for member in owners.get(owner, []):
                    if member.disposition in {"support", "error"}:
                        required[
                            (member.owner, member.jvm_name, member.jvm_descriptor)
                        ] = member
                        pending.append(member)
        return tuple(required.values())

    def capability_report(self) -> dict[str, Any]:
        """Group exact parameters by reusable capability, without claiming coverage."""
        families: dict[str, Counter[str]] = defaultdict(Counter)
        gaps = []
        source_types: Counter[str] = Counter()
        slot_arguments: Counter[str] = Counter()
        for declaration in self.ui:
            source_types.update(_classifiers(declaration.document))
            for receiver in (
                declaration.receiver,
                declaration.dispatch_receiver,
                *declaration.context_receivers,
            ):
                if receiver is not None:
                    families["receiver"][receiver.classifier] += 1
            for parameter in declaration.parameters:
                families[parameter.kind.value][parameter.type.classifier] += 1
                gaps.append(
                    {
                        "component": declaration.name,
                        "owner": declaration.owner,
                        "overload": declaration.jvm_descriptor,
                        "parameter": parameter.name,
                        "kind": parameter.kind.value,
                        "classifier": parameter.type.classifier,
                        "status": "needs-capability-audit",
                        "functionTypes": [
                            t.document
                            for _, t in parameter.type.arguments
                            if t is not None
                        ]
                        if parameter.kind != Kind.VALUE
                        else [],
                    }
                )
                if parameter.kind == Kind.SLOT:
                    slot_arguments.update(
                        t.classifier
                        for _, t in parameter.type.arguments[:-1]
                        if t is not None
                    )
        return {
            "bom": self.bom,
            "compiler": self.compiler,
            "status": "discovery-only",
            "componentNames": len({d.name for d in self.ui}),
            "overloads": len(self.ui),
            "families": {
                k: dict(sorted(v.items())) for k, v in sorted(families.items())
            },
            "gaps": gaps,
            "extractionErrors": self.document["diagnostics"],
            "requiredSupportSignatures": len(self.required_support),
            "controllerCandidates": {
                k: v for k, v in sorted(source_types.items()) if k.endswith("State")
            },
            "scopeCandidates": {
                k: v for k, v in sorted(source_types.items()) if k.endswith("Scope")
            },
            "resourceCandidates": {
                k: v
                for k, v in sorted(source_types.items())
                if k.endswith(
                    (
                        "Colors",
                        "Shape",
                        "Brush",
                        "InteractionSource",
                        "Elevation",
                        "FontFamily",
                    )
                )
            },
            "slotArguments": dict(sorted(slot_arguments.items())),
        }


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


UNRESOLVED = {"kind": "unsupported", "reason": "source could not be pinned"}
"""Reported per binding, so one ambiguous declaration never blinds the catalog."""


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
        data["toolHash"]
        == hashlib.sha256(
            (
                Path(__file__).resolve().parents[2] / "android/tools/SourceDefaults.kt"
            ).read_bytes()
        ).hexdigest(),
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


def _classifiers(value: Any):
    if isinstance(value, dict):
        if "classifier" in value:
            yield value["classifier"]
        for child in value.values():
            yield from _classifiers(child)
    elif isinstance(value, list):
        for child in value:
            yield from _classifiers(child)


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
    for artifact in artifacts.values():
        module, version = artifact["coordinate"].rsplit(":", 1)
        expected = provenance["bomConstraints"].get(module)
        if expected is not None:
            _require(
                version == expected, "resolved artifact differs from BOM constraint"
            )
        _require(artifact["variant"] in {"androidJvm", None}, "non-Android artifact")
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
                artifacts[record["artifact"]]["variant"] == "androidJvm",
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
