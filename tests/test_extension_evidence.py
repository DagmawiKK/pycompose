"""Evidence records report stage outcomes, staleness and honest overall status."""

import json

import pytest

from pycompose.cli.extensions.evidence import (
    STAGES,
    EvidenceRecord,
    Target,
    fingerprint,
    load_records,
    record_status,
    summarize,
)
from pycompose.errors import StateError

FINGERPRINT = "sha256:" + "a" * 64


def record(**overrides: object) -> EvidenceRecord:
    fields: dict[str, object] = {
        "format": 1,
        "extension": "pycompose.sqlite",
        "version": "1.0.0",
        "scenario": "pycompose.sqlite.transaction",
        "scenarioVersion": 1,
        "fingerprint": FINGERPRINT,
        "target": {"python": "3.12", "abis": ["arm64-v8a"], "minSdk": 24},
        "stages": dict.fromkeys(STAGES, "pass"),
        "cleanup": "pass",
        "recorded": "2026-10-18T00:00:00Z",
    }
    fields.update(overrides)
    return EvidenceRecord.parse(json.dumps(fields))


def test_declared_scenario_without_a_record_is_untested() -> None:
    view, counts = summarize(
        {"pycompose.sqlite": ["pycompose.sqlite.transaction"]},
        {"pycompose.sqlite.transaction": FINGERPRINT},
    )

    assert view["pycompose.sqlite"]["pycompose.sqlite.transaction"] == {
        "status": "untested"
    }
    assert counts == {"untested": 1}


def test_another_targets_run_is_partial_coverage_not_untested() -> None:
    """Partial coverage must stay visible instead of reading as never tried."""
    both = Target(python="3.12", abis=("arm64-v8a", "x86_64"), min_sdk=24)
    observed = record(target={"python": "3.12", "abis": ["arm64-v8a"], "minSdk": 24})

    view, counts = summarize(
        {"pycompose.sqlite": ["pycompose.sqlite.transaction"]},
        {"pycompose.sqlite.transaction": FINGERPRINT},
        [observed],
        both,
    )

    entry = view["pycompose.sqlite"]["pycompose.sqlite.transaction"]
    assert entry["status"] == "partial"
    assert entry["observedTargets"] == [["arm64-v8a"]]
    assert counts == {"partial": 1}


def test_partial_coverage_still_shows_a_failure_that_was_observed_elsewhere() -> None:
    """A failure on one target must not be hidden behind partial coverage."""
    both = Target(python="3.12", abis=("arm64-v8a", "x86_64"), min_sdk=24)
    failed = record(
        target={"python": "3.12", "abis": ["arm64-v8a"], "minSdk": 24},
        stages={**dict.fromkeys(STAGES, "pass"), "operations": "fail"},
    )

    view, _ = summarize(
        {"pycompose.sqlite": ["pycompose.sqlite.transaction"]},
        {"pycompose.sqlite.transaction": FINGERPRINT},
        [failed],
        both,
    )

    entry = view["pycompose.sqlite"]["pycompose.sqlite.transaction"]
    assert entry["status"] == "partial"
    assert entry["record"]["stages"]["operations"] == "fail"


def test_all_stages_passing_with_matching_fingerprint_is_verified() -> None:
    assert record_status(record(), FINGERPRINT) == "verified"


def test_a_failed_stage_makes_the_scenario_failed() -> None:
    failed = record(stages={**dict.fromkeys(STAGES, "pass"), "operations": "fail"})

    assert record_status(failed, FINGERPRINT) == "failed"


def test_a_changed_fingerprint_makes_a_passing_record_stale() -> None:
    assert record_status(record(), "sha256:" + "b" * 64) == "stale"


def test_incomplete_cleanup_is_not_verified() -> None:
    assert record_status(record(cleanup="notRun"), FINGERPRINT) == "incomplete"


def test_a_missing_stage_is_not_verified() -> None:
    partial = dict.fromkeys(STAGES, "pass")
    del partial["operations"]
    assert record_status(record(stages=partial), FINGERPRINT) == "incomplete"


def test_parsing_rejects_unknown_fields_and_other_formats() -> None:
    with pytest.raises(StateError, match="unknown evidence fields"):
        record(extra="value")  # type: ignore[arg-type]
    with pytest.raises(StateError, match="unsupported evidence format"):
        record(format=2)  # type: ignore[arg-type]


def test_parsing_rejects_unknown_stages_and_statuses() -> None:
    with pytest.raises(StateError, match="unknown evidence stage"):
        record(stages={**dict.fromkeys(STAGES, "pass"), "guess": "pass"})
    with pytest.raises(StateError, match="unknown evidence status"):
        record(stages={**dict.fromkeys(STAGES, "pass"), "operations": "great"})


def test_parsing_keeps_every_declared_stage_independently() -> None:
    mixed = {**dict.fromkeys(STAGES, "pass"), "resolution": "unavailable"}

    view = record(stages=mixed).to_json()

    assert view["stages"]["resolution"] == "unavailable"
    assert view["stages"]["packaging"] == "pass"


def test_load_rejects_a_document_without_the_format_field() -> None:
    with pytest.raises(StateError, match="evidence format"):
        load_records('{"records": []}')


def test_load_rejects_unknown_top_level_document_keys() -> None:
    with pytest.raises(StateError, match="unknown evidence fields"):
        load_records(json.dumps({"format": 1, "records": [], "endorsements": []}))


def test_load_refuses_an_oversized_document() -> None:
    oversized = json.dumps({"format": 1, "records": [], "pad": "x" * (4 * 1024 * 1024)})

    with pytest.raises(StateError, match="too large"):
        load_records(oversized)


def test_a_record_cannot_smuggle_an_unsupported_format_past_the_document() -> None:
    document = json.dumps({"format": 1, "records": [{"format": 99}]})

    with pytest.raises(StateError, match="unsupported evidence format"):
        load_records(document)


def test_a_record_missing_a_required_field_is_rejected_without_a_keyerror() -> None:
    entry = json.loads(json.dumps(record().to_json()))
    del entry["cleanup"]

    with pytest.raises(StateError, match="evidence record needs"):
        load_records(json.dumps({"format": 1, "records": [entry]}))


def test_evidence_for_one_abi_does_not_verify_the_whole_target() -> None:
    """Packaging two ABIs is not executing on both."""
    observed = record(target={"python": "3.12", "abis": ["arm64-v8a"], "minSdk": 24})
    both = Target(python="3.12", abis=("arm64-v8a", "x86_64"), min_sdk=24)

    assert record_status(observed, FINGERPRINT, target=both) == "incomplete"


def test_another_targets_failure_is_not_this_targets_failure() -> None:
    """An arm64 failure is not an x86_64 incompatibility."""
    failed = record(
        target={"python": "3.12", "abis": ["arm64-v8a"], "minSdk": 24},
        stages={**dict.fromkeys(STAGES, "pass"), "operations": "fail"},
    )
    other = Target(python="3.12", abis=("x86_64",), min_sdk=24)

    assert record_status(failed, FINGERPRINT, target=other) == "incomplete"


def test_the_same_failure_on_the_same_target_still_fails() -> None:
    failed = record(stages={**dict.fromkeys(STAGES, "pass"), "operations": "fail"})
    target = Target(python="3.12", abis=("arm64-v8a",), min_sdk=24)

    assert record_status(failed, FINGERPRINT, target=target) == "failed"


def test_a_record_for_another_target_does_not_replace_this_targets_record() -> None:
    """A second target's run must not hide the first target's passing record."""
    both = Target(python="3.12", abis=("arm64-v8a", "x86_64"), min_sdk=24)
    other = Target(python="3.12", abis=("x86_64",), min_sdk=24)
    passing = record(target=both.to_json())
    failing = record(
        target=other.to_json(),
        stages={**dict.fromkeys(STAGES, "pass"), "import": "fail"},
    )

    view, _ = summarize(
        {"pycompose.sqlite": ["pycompose.sqlite.transaction"]},
        {"pycompose.sqlite.transaction": FINGERPRINT},
        [passing, failing],
        both,
    )

    entry = view["pycompose.sqlite"]["pycompose.sqlite.transaction"]
    assert entry["status"] == "verified"


def test_evidence_for_the_same_target_verifies() -> None:
    target = Target(python="3.12", abis=("arm64-v8a",), min_sdk=24)

    assert record_status(record(), target=target, fingerprint=FINGERPRINT) == "verified"


def test_a_fingerprint_depends_on_every_input_not_its_order() -> None:
    inputs = {
        "framework": "0.1.0",
        "extension": "pycompose.sqlite",
        "requirements": ("httpx>=0.27",),
    }

    assert fingerprint(inputs) == fingerprint(dict(reversed(list(inputs.items()))))
    assert fingerprint(inputs).startswith("sha256:")


def test_changing_one_fingerprint_input_changes_the_digest() -> None:
    base = {"framework": "0.1.0", "extension": "pycompose.sqlite"}

    assert fingerprint(base) != fingerprint({**base, "framework": "0.1.1"})


def test_a_fingerprint_ignores_volatile_timestamps() -> None:
    base = {"framework": "0.1.0"}

    assert fingerprint({**base, "recorded": "2026-10-18T00:00:00Z"}) == fingerprint(
        {**base, "recorded": "2026-10-19T00:00:00Z"}
    )
