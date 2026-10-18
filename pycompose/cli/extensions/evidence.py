"""Versioned compatibility evidence: stages, fingerprints and honest status.

An evidence record reports what was observed for one declared scenario on one
target. It is data, not a support endorsement: a record only verifies a scenario
whose declared stages and cleanup all passed, on matching inputs, for that exact
target. A failure stays a failure even when the inputs moved on; a record whose
inputs changed is stale, not wrong.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from pycompose.errors import StateError

FORMAT = 1
#: An evidence document is project data read before anything runs; a bound keeps
#: a hand-edited or generated file from exhausting memory during discovery.
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
#: Inputs whose change makes a record stale rather than wrong.
VOLATILE = frozenset({"recorded", "timestamp", "elapsed"})
#: The independent stages a scenario must show before it can read as verified.
STAGES = (
    "declaration",
    "resolution",
    "packaging",
    "import",
    "operations",
    "integration",
    "platform",
)
Status = Literal["pass", "fail", "notRun", "skipped", "unavailable", "unsupported"]
_STATUSES: frozenset[str] = frozenset(
    {"pass", "fail", "notRun", "skipped", "unavailable", "unsupported"}
)
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise StateError(f"evidence {field} must be a nonempty string")
    return value


def _status(value: object, field: str) -> Status:
    if value not in _STATUSES:
        raise StateError(f"unknown evidence status for {field}")
    return cast("Status", value)


def fingerprint(inputs: Mapping[str, object]) -> str:
    """Digest the inputs an observation depends on, excluding volatile fields.

    Args:
        inputs: Named input values: framework and definition identity, scenario
            revision, resolved artifacts, build mode, target and configuration.
            Timestamps and other volatile readings are excluded.

    Returns:
        ``sha256:<64 hex digits>`` over the canonical JSON encoding.
    """
    stable = {
        key: value for key, value in inputs.items() if key.lower() not in VOLATILE
    }
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":"), default=list)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class Target:
    """The target facts a record was observed against.

    Attributes:
        python: Target Python version, never the desktop interpreter.
        abis: ABI actually executed; packaged ABIs are recorded separately.
        min_sdk: Lowest device API used.
    """

    python: str
    abis: tuple[str, ...]
    min_sdk: int

    def to_json(self) -> dict[str, object]:
        """Return the target as canonical JSON data.

        Returns:
            Plain data with the same field names as the document.
        """
        return {"python": self.python, "abis": list(self.abis), "minSdk": self.min_sdk}

    @classmethod
    def parse(cls, raw: object) -> Target:
        """Validate target facts from decoded JSON.

        Args:
            raw: Decoded JSON object.

        Returns:
            The validated target.

        Raises:
            StateError: If any target fact is missing or malformed.
        """
        if not isinstance(raw, dict) or set(raw) != {"python", "abis", "minSdk"}:
            raise StateError("evidence target needs python, abis and minSdk")
        abis = raw["abis"]
        if (
            not isinstance(abis, list)
            or not abis
            or not all(isinstance(abi, str) and abi for abi in abis)
        ):
            raise StateError("evidence target abis must be nonempty strings")
        if type(raw["minSdk"]) is not int or raw["minSdk"] < 1:
            raise StateError("evidence target minSdk must be a positive integer")
        return cls(_text(raw["python"], "target python"), tuple(abis), raw["minSdk"])


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """What one runner observed for one scenario on one target.

    Attributes:
        extension: Namespaced extension identity that declared the scenario.
        version: Declared extension version, not resolved dependency identity.
        scenario: Declared scenario identity.
        scenario_version: Scenario's own revision.
        fingerprint: Digest of the inputs this observation depends on.
        target: Target facts observed.
        stages: Per-stage outcomes, independent of one another.
        cleanup: Whether the scenario's cleanup requirement was met.
        recorded: UTC timestamp, excluded from the fingerprint.
    """

    extension: str
    version: str
    scenario: str
    scenario_version: int
    fingerprint: str
    target: Target
    stages: Mapping[str, Status]
    cleanup: Status
    recorded: str

    @classmethod
    def parse(cls, source: str) -> EvidenceRecord:
        """Validate one evidence record without executing anything it describes.

        Args:
            source: JSON text for a single record, including its format field.

        Returns:
            The immutable validated record.

        Raises:
            StateError: If the format, fields, stages or statuses are invalid.
        """
        try:
            raw = json.loads(source)
        except ValueError as exc:
            raise StateError("invalid evidence JSON") from exc
        if not isinstance(raw, dict):
            raise StateError("evidence record must be an object")
        required = {
            "extension",
            "version",
            "scenario",
            "scenarioVersion",
            "fingerprint",
            "target",
            "stages",
            "cleanup",
            "recorded",
        }
        if raw.get("format") != FORMAT:
            raise StateError(f"unsupported evidence format (expected {FORMAT})")
        if set(raw) - required - {"format"}:
            raise StateError("unknown evidence fields")
        if missing := sorted(required - set(raw)):
            raise StateError(f"evidence record needs {', '.join(missing)}")
        stages = raw["stages"]
        if not isinstance(stages, dict) or set(stages) - set(STAGES):
            raise StateError("unknown evidence stage")
        if type(raw["scenarioVersion"]) is not int or raw["scenarioVersion"] < 1:
            raise StateError("evidence scenarioVersion must be a positive integer")
        digest = _text(raw["fingerprint"], "fingerprint")
        if not _FINGERPRINT.fullmatch(digest):
            raise StateError("evidence fingerprint must be sha256:<64 hex digits>")
        return cls(
            _text(raw["extension"], "extension"),
            _text(raw["version"], "version"),
            _text(raw["scenario"], "scenario"),
            raw["scenarioVersion"],
            digest,
            Target.parse(raw["target"]),
            {stage: _status(stages[stage], stage) for stage in stages},
            _status(raw["cleanup"], "cleanup"),
            _text(raw["recorded"], "recorded"),
        )

    def to_json(self) -> dict[str, object]:
        """Return the record as canonical JSON data.

        Returns:
            Plain data with the same field names as the document.
        """
        return {
            "format": FORMAT,
            "extension": self.extension,
            "version": self.version,
            "scenario": self.scenario,
            "scenarioVersion": self.scenario_version,
            "fingerprint": self.fingerprint,
            "target": self.target.to_json(),
            "stages": dict(sorted(self.stages.items())),
            "cleanup": self.cleanup,
            "recorded": self.recorded,
        }


def record_status(
    record: EvidenceRecord, fingerprint: str, target: Target | None = None
) -> str:
    """Report one record's honest status against the current inputs.

    Args:
        record: Previously observed scenario evidence.
        fingerprint: Digest of the inputs the record would depend on now.
        target: Target this status is being reported for. A record observed on
            another target cannot verify this one; packaging an ABI is not
            executing on it.

    Returns:
        ``failed``, ``stale``, ``incomplete`` or ``verified``. Nothing is
        verified unless every declared stage and the cleanup requirement passed
        for this exact target. A failure on another target is not this target's
        failure, so the target is compared before the stages.
    """
    if target is not None and record.target != target:
        # Another target's result is not this target's verdict, in either
        # direction: an arm64 failure is not an x86_64 incompatibility.
        return "incomplete"
    if any(status == "fail" for status in record.stages.values()) or (
        record.cleanup == "fail"
    ):
        return "failed"
    if record.fingerprint != fingerprint:
        return "stale"
    if any(record.stages.get(stage) != "pass" for stage in STAGES) or (
        record.cleanup != "pass"
    ):
        return "incomplete"
    return "verified"


def summarize(
    declared: Mapping[str, Sequence[str]],
    fingerprints: Mapping[str, str],
    records: Sequence[EvidenceRecord] = (),
    target: Target | None = None,
) -> tuple[dict[str, dict[str, object]], dict[str, int]]:
    """Report every declared scenario as verified, stale, incomplete or untested.

    Args:
        declared: Scenario identities keyed by extension identity.
        fingerprints: Current input digest per scenario identity.
        records: Previously observed records, in any order.
        target: Target being reported; a record for another target is not a pass.

    Returns:
        A per-extension mapping of scenario identity to its status and record,
        together with the count of scenarios in each status.
    """
    latest: dict[tuple[str, str, Target], EvidenceRecord] = {}
    others: dict[tuple[str, str], list[EvidenceRecord]] = {}
    for observed in records:
        # Keyed by target too: a later run on one target must not silently
        # replace an earlier observation of another.
        latest[(observed.extension, observed.scenario, observed.target)] = observed
        seen = others.setdefault((observed.extension, observed.scenario), [])
        if all(item != observed for item in seen):
            seen.append(observed)
    view: dict[str, dict[str, object]] = {}
    for extension, scenarios in sorted(declared.items()):
        entries: dict[str, object] = {}
        for scenario in sorted(scenarios):
            record = (
                None if target is None else latest.get((extension, scenario, target))
            )
            if record is None:
                # Nothing ran on this exact target. A run on another target is
                # partial coverage and must stay visible: reporting it as
                # untested would bury a failure that really was observed.
                elsewhere = others.get((extension, scenario), [])
                if not elsewhere:
                    entries[scenario] = {"status": "untested"}
                    continue
                newest = max(elsewhere, key=lambda item: item.recorded)
                entries[scenario] = {
                    "status": "partial",
                    "observedTargets": [sorted(item.target.abis) for item in elsewhere],
                    "record": newest.to_json(),
                }
                continue
            entries[scenario] = {
                "status": record_status(record, fingerprints[scenario], target),
                "record": record.to_json(),
            }
        view[extension] = entries
    counts: dict[str, int] = {}
    for entries in view.values():
        for entry in entries.values():
            if isinstance(entry, dict):
                status = str(entry["status"])
                counts[status] = counts.get(status, 0) + 1
    return view, counts


def load_records(source: str) -> tuple[EvidenceRecord, ...]:
    """Read an evidence document without importing or running any scenario.

    Args:
        source: JSON text containing a ``format`` and a ``records`` array.

    Returns:
        Every validated record, in document order.

    Raises:
        StateError: If the document is too large, has unknown top-level keys, or
            if any record is invalid.
    """
    if len(source) > MAX_DOCUMENT_BYTES:
        raise StateError("evidence document is too large to read")
    try:
        raw = json.loads(source)
    except ValueError as exc:
        raise StateError("invalid evidence JSON") from exc
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise StateError(f"unsupported evidence format (expected {FORMAT})")
    if set(raw) - {"format", "records"}:
        raise StateError("unknown evidence fields")
    entries = raw.get("records")
    if not isinstance(entries, list):
        raise StateError("evidence document needs a records array")
    records = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise StateError("evidence record must be an object")
        # A record's own format is validated, never overwritten by the
        # document's: silently upgrading it would make the per-record
        # version gate unreachable.
        records.append(
            EvidenceRecord.parse(
                json.dumps(entry if "format" in entry else {**entry, "format": FORMAT})
            )
        )
    return tuple(records)
