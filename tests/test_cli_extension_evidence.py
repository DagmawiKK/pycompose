"""`pycompose extensions` reports evidence beside its plan, read-only."""

import hashlib
import json
from pathlib import Path

from test_cli_init import cli

STAGES = (
    "declaration",
    "resolution",
    "packaging",
    "import",
    "operations",
    "integration",
    "platform",
)
#: Framework, definition identity, declared requirement, template version, target
#: and configuration the fingerprint must cover. Expected values are literals.
PYTHON_VERSION = "3.12"
ABIS = ["arm64-v8a", "x86_64"]
MIN_SDK = 24


def fingerprint() -> str:
    """Compute the expected digest independently of the CLI implementation."""
    stable = {
        "abis": ABIS,
        "definitionVersion": "1.0.0",
        "extension": "example.custom",
        "framework": "0.1.0",
        "minSdk": MIN_SDK,
        "permissions": [],
        "python": PYTHON_VERSION,
        "requirements": ["some-library>=1"],
        "scenario": "example.roundtrip",
        "scenarioVersion": 1,
        "template": "0.7.0",
    }
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(encoded.encode()).hexdigest()}"


def evidence_document(
    digest: str | None = None, *, abis: list[str] | None = None, **stages: str
) -> str:
    record = {
        "extension": "example.custom",
        "version": "1.0.0",
        "scenario": "example.roundtrip",
        "scenarioVersion": 1,
        "fingerprint": digest or fingerprint(),
        "target": {
            "python": PYTHON_VERSION,
            "abis": abis or ABIS,
            "minSdk": MIN_SDK,
        },
        "stages": {**dict.fromkeys(STAGES, "pass"), **stages},
        "cleanup": "pass",
        "recorded": "2026-10-18T00:00:00Z",
    }
    return json.dumps({"format": 1, "records": [record]})


def prepare(tmp_path: Path, *, document: str | None = None) -> Path:
    assert cli(tmp_path, "init", "demo").returncode == 0
    project = tmp_path / "demo"
    (project / "custom.toml").write_text(
        'format = 1\ninterface = 1\nid = "example.custom"\nversion = "1.0.0"\n'
        'requirements = ["some-library>=1"]\nscenarios = ["example.roundtrip"]\n'
        '[requires]\n"python.serial" = 1\n'
    )
    with (project / "pycompose.toml").open("a") as stream:
        stream.write('\n[extensions]\ndefinitions = ["custom.toml"]\n')
    if document is not None:
        (project / "evidence.json").write_text(document)
    return project


def test_a_declared_scenario_reads_as_untested_without_records(tmp_path) -> None:
    project = prepare(tmp_path)

    result = cli(project, "extensions", "evidence")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["evidence"] == {
        "example.custom": {"example.roundtrip": {"status": "untested"}}
    }
    assert report["summary"] == {"untested": 1}


def test_a_matching_record_reads_as_verified(tmp_path) -> None:
    project = prepare(tmp_path, document=evidence_document())

    result = cli(project, "extensions", "evidence")

    assert result.returncode == 0, result.stderr
    entry = json.loads(result.stdout)["evidence"]["example.custom"]["example.roundtrip"]
    assert entry["status"] == "verified"
    assert entry["record"]["target"]["abis"] == ["arm64-v8a", "x86_64"]


def test_evidence_for_one_abi_reports_partial_coverage_for_the_target(tmp_path) -> None:
    """An arm64-only run is visible partial coverage, never a two-ABI pass."""
    project = prepare(tmp_path, document=evidence_document(abis=["arm64-v8a"]))

    entry = json.loads(cli(project, "extensions", "evidence").stdout)["evidence"][
        "example.custom"
    ]["example.roundtrip"]

    assert entry["status"] == "partial"
    assert entry["observedTargets"] == [["arm64-v8a"]]


def test_changing_the_template_version_makes_a_record_stale(tmp_path) -> None:
    project = prepare(tmp_path, document=evidence_document())
    config = project / "pycompose.toml"
    config.write_text(config.read_text().replace("0.7.0", "0.7.1"))

    report = json.loads(cli(project, "extensions", "evidence").stdout)

    entry = report["evidence"]["example.custom"]["example.roundtrip"]
    assert entry["status"] == "stale"
    assert report["summary"] == {"stale": 1}


def test_an_unavailable_stage_is_never_verified(tmp_path) -> None:
    project = prepare(tmp_path, document=evidence_document(packaging="unavailable"))

    report = json.loads(cli(project, "extensions", "evidence").stdout)

    entry = report["evidence"]["example.custom"]["example.roundtrip"]
    assert entry["status"] == "incomplete"
    assert report["summary"] == {"incomplete": 1}


def test_an_import_only_record_is_not_a_platform_pass(tmp_path) -> None:
    project = prepare(tmp_path, document=evidence_document(platform="notRun"))

    entry = json.loads(cli(project, "extensions", "evidence").stdout)["evidence"][
        "example.custom"
    ]["example.roundtrip"]

    assert entry["status"] == "incomplete"


def test_a_failed_stage_outranks_a_changed_fingerprint(tmp_path) -> None:
    project = prepare(
        tmp_path, document=evidence_document("sha256:" + "b" * 64, operations="fail")
    )

    entry = json.loads(cli(project, "extensions", "evidence").stdout)["evidence"][
        "example.custom"
    ]["example.roundtrip"]

    assert entry["status"] == "failed"


def test_evidence_reading_never_imports_candidate_implementations(tmp_path) -> None:
    """A sentinel module fails loudly if discovery executes anything.

    The candidate package sits next to the definition, importing a module that
    raises on import: metadata reading must never reach it.
    """
    project = prepare(tmp_path)
    (project / "sentinel.py").write_text(
        "raise AssertionError('evidence discovery imported app code')\n"
    )
    (project / "my_recipe.py").write_text(
        "import sentinel\n"
        "from pycompose.extensions import Resource\n"
        "def open_resource(*, capacity=16):\n"
        "    return Resource(lambda: {}, close=lambda value: None,\n"
        "                    capacity=capacity)\n"
    )

    plan = cli(project, "extensions", "plan")
    report = cli(project, "extensions", "evidence")

    assert plan.returncode == 0, plan.stderr
    assert report.returncode == 0, report.stderr
    assert "Traceback" not in report.stderr


def test_an_invalid_evidence_document_fails_with_an_actionable_message(
    tmp_path,
) -> None:
    project = prepare(tmp_path, document='{"records": []}')

    result = cli(project, "extensions", "evidence")

    assert result.returncode == 2
    assert "evidence format" in result.stderr
    assert "Traceback" not in result.stderr


def test_the_plan_keeps_reporting_unverified_when_no_evidence_exists(tmp_path) -> None:
    project = prepare(tmp_path)

    plan = json.loads(cli(project, "extensions", "plan").stdout)

    assert plan["evidence"] == "unverified"
    assert plan["observed"] == {
        "example.custom": {"example.roundtrip": {"status": "untested"}}
    }
    assert plan["checks"]["operations"] == "notRun"


def test_the_plan_never_promotes_observed_evidence_into_its_own_claim(tmp_path) -> None:
    """The planner ran nothing, so its own verdict stays unverified."""
    project = prepare(tmp_path, document=evidence_document())

    plan = json.loads(cli(project, "extensions", "plan").stdout)

    assert plan["evidence"] == "unverified"
    observed = plan["observed"]["example.custom"]["example.roundtrip"]
    assert observed["status"] == "verified"
    assert observed["record"]["scenario"] == "example.roundtrip"
    assert plan["observedSummary"] == {"verified": 1}
    assert plan["errors"] == []
