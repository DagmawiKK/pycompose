"""The classpath-dump data types: declared annotations as typed records.

The ``dumpComposeDefaults`` Gradle task writes a JSON dump of every pinned
declaration; these frozen dataclasses are its typed view. The reader and its
validators live in ``classpath_dump``.
"""

from __future__ import annotations

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

    @property
    def class_modality(self) -> str | None:
        """Kotlin modality of the owning class, when the declaration has one."""
        modality = self.document.get("classModality")
        return modality if isinstance(modality, str) else None

    @property
    def enum_entries(self) -> tuple[str, ...]:
        """Entry names when the owner is an enum class, else nothing."""
        entries = self.document.get("enumEntries")
        return tuple(entries) if isinstance(entries, list) else ()

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
class KotlinClass:
    """One class the pin declares, including classes with no members of their own.

    Declaration records carry their owner's hierarchy, so a class that declares
    nothing never appears there. ``Alignment.Vertical`` is exactly that shape:
    it is a sibling of ``Alignment``, and without its own record a member
    vocabulary cannot tell an assignable type from a neighbouring one.
    """

    artifact: str
    owner: str
    classifier: str
    package: str
    class_kind: str
    class_modality: str | None
    visibility: str
    supertypes: tuple[str, ...]
    document: dict[str, Any]

    @classmethod
    def read(cls, data: dict[str, Any]) -> KotlinClass:
        return cls(
            artifact=data["artifact"],
            owner=data["owner"],
            classifier=data["classifier"],
            package=data["package"],
            class_kind=data["classKind"],
            class_modality=data.get("classModality"),
            visibility=data["classVisibility"],
            supertypes=tuple(
                node["classifier"] for node in data.get("classSupertypes") or []
            ),
            document=data,
        )


@dataclass(frozen=True)
class Inventory:
    """Artifact provenance, declarations, and class facts, before any approval."""

    bom: str
    compiler: str
    declarations: tuple[Declaration, ...]
    classes: tuple[KotlinClass, ...]
    document: dict[str, Any]

    @property
    def ui(self) -> tuple[Declaration, ...]:
        return tuple(d for d in self.declarations if d.disposition == "ui")

    @property
    def required_support(self) -> tuple[Declaration, ...]:
        """Transitive member signatures of classes referenced by public components.

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


def _classifiers(value: Any):
    if isinstance(value, dict):
        if "classifier" in value:
            yield value["classifier"]
        for child in value.values():
            yield from _classifiers(child)
    elif isinstance(value, list):
        for child in value:
            yield from _classifiers(child)
