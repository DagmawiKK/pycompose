"""Versioned, side-effect-free extension definitions and capability planning."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pycompose.errors import StateError

_ID = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item and not any(ord(c) < 32 for c in item)
        for item in value
    ):
        raise StateError(f"extension {field} must be an array of nonempty strings")
    if len(value) != len(set(value)):
        raise StateError(f"duplicate extension {field}")
    return tuple(value)


def _contracts(value: object) -> Mapping[str, int]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str)
        and _ID.fullmatch(key)
        and type(version) is int
        and version > 0
        for key, version in value.items()
    ):
        raise StateError("capabilities must map namespaced ids to positive versions")
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class Definition:
    """An opt-in recipe, not executable discovery metadata.

    Attributes:
        id: Namespaced contributor-owned identity.
        version: Recipe semantic version, not package compatibility evidence.
        requires: Required capability contract major versions.
        optional: Capabilities whose absence is reported without substitution.
        requirements: Named Python requirements, installed by the Android toolchain.
        modules: Optional bundled Python implementation modules to stage.
        scenarios: Names of operations needing explicit compatibility evidence.
        python_versions: Declared interpreter versions, or empty when unrestricted.
        abis: Declared Android ABIs, or empty when unrestricted.
        min_sdk: Minimum device API required by this integration.
    """

    id: str
    version: str
    requires: Mapping[str, int]
    optional: Mapping[str, int]
    requirements: tuple[str, ...] = ()
    modules: tuple[str, ...] = ()
    scenarios: tuple[str, ...] = ()
    python_versions: tuple[str, ...] = ()
    abis: tuple[str, ...] = ()
    min_sdk: int = 24

    @classmethod
    def parse(cls, source: str) -> Definition:
        """Validate TOML without importing a package or executing its entries.

        Args:
            source: Definition text using format/interface version one.

        Returns:
            An immutable validated definition.

        Raises:
            StateError: If the definition is malformed or needs another interface.
        """
        try:
            raw = tomllib.loads(source)
        except ValueError as exc:
            raise StateError("invalid extension TOML") from exc
        allowed = {
            "format",
            "interface",
            "id",
            "version",
            "requires",
            "optional",
            "requirements",
            "modules",
            "scenarios",
            "python_versions",
            "abis",
            "min_sdk",
        }
        if set(raw) - allowed:
            raise StateError("unknown extension fields")
        if any(
            type(raw.get(key)) is not int or raw[key] != 1
            for key in ("format", "interface")
        ):
            raise StateError("unsupported extension format or interface (expected 1)")
        identity, version = raw.get("id"), raw.get("version")
        if not isinstance(identity, str) or not _ID.fullmatch(identity):
            raise StateError("extension id must be namespaced")
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise StateError("extension version must be major.minor.patch")
        modules = _strings(raw.get("modules", []), "modules")
        min_sdk = raw.get("min_sdk", 24)
        if type(min_sdk) is not int or min_sdk < 1:
            raise StateError("extension min_sdk must be a positive integer")
        if any(
            not re.fullmatch(r"pycompose\.integrations\.[a-z][a-z0-9_]*", m)
            for m in modules
        ):
            raise StateError("bundled modules must belong to pycompose.integrations")
        return cls(
            identity,
            version,
            _contracts(raw.get("requires", {})),
            _contracts(raw.get("optional", {})),
            _strings(raw.get("requirements", []), "requirements"),
            modules,
            _strings(raw.get("scenarios", []), "scenarios"),
            _strings(raw.get("python_versions", []), "python_versions"),
            _strings(raw.get("abis", []), "abis"),
            min_sdk,
        )


def plan(
    definitions: tuple[Definition, ...],
    capabilities: Mapping[str, int],
    *,
    python_version: str = "3.12",
    abis: tuple[str, ...] = ("arm64-v8a", "x86_64"),
    min_sdk: int = 24,
) -> dict[str, object]:
    """Check requirements against explicitly available capability versions.

    Args:
        definitions: Selected recipes; no implementations are imported.
        capabilities: Contracts actually provided by the selected host/runtime.
        python_version: Configured target Python, never the desktop interpreter.
        abis: Configured Android ABIs, not the desktop machine architecture.
        min_sdk: Lowest supported device API for the host.

    Returns:
        A deterministic read-only report. Evidence remains unverified.

    Raises:
        StateError: If extension identities are duplicated.
    """
    identities = [definition.id for definition in definitions]
    if len(identities) != len(set(identities)):
        raise StateError("duplicate extension id")
    missing: list[str] = []
    optional: list[str] = []
    for definition in definitions:
        if (
            definition.python_versions
            and python_version not in definition.python_versions
        ):
            missing.append(f"{definition.id} -> Python {python_version} not declared")
        if definition.abis:
            missing.extend(
                f"{definition.id} -> ABI {abi} not declared"
                for abi in abis
                if abi not in definition.abis
            )
        if definition.min_sdk > min_sdk:
            missing.append(
                f"{definition.id} -> needs minSdk {definition.min_sdk} "
                f"(host floor {min_sdk})"
            )
        for contracts, issues in (
            (definition.requires, missing),
            (definition.optional, optional),
        ):
            for key, version in sorted(contracts.items()):
                if capabilities.get(key) != version:
                    issues.append(f"{definition.id} -> {key}@{version}")
    return {
        "format": 1,
        "extensions": identities,
        "requirements": list(
            dict.fromkeys(item for d in definitions for item in d.requirements)
        ),
        "modules": sorted({item for d in definitions for item in d.modules}),
        "scenarios": sorted({item for d in definitions for item in d.scenarios}),
        "missingOptional": optional,
        "errors": missing,
        "evidence": "unverified",
        "checks": {
            "capabilities": "failed" if missing else "passed",
            "resolution": "notRun",
            "packaging": "notRun",
            "import": "notRun",
            "operations": "notRun",
        },
    }
