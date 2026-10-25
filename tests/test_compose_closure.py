"""The Compose extraction closure is ratified policy, not whatever resolves.

``android/compose-closure.json`` is consumed by ``dumpComposeApi`` and audited
here: the ratified group set, the classification of every group and artifact,
and -- when a local inventory exists -- the exact artifacts and digests that
run produced.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLOSURE_PATH = ROOT / "android" / "compose-closure.json"
INVENTORY_PATH = ROOT / "android" / "build" / "compose-api" / "inventory.json"
EXTRACTOR = ROOT / "android" / "compose-extract"
"""The extraction module: its build script resolves, its tool verifies."""

# group -> (status, category, domain, design)
GROUPS: dict[str, tuple[str, str, str, str | None]] = {
    "androidx.activity": ("extracted", "app-surface", "activity", None),
    "androidx.compose.animation": ("extracted", "app-surface", "animation", None),
    "androidx.compose.foundation": ("extracted", "app-surface", "foundation", None),
    "androidx.compose.material": ("extracted", "app-surface", "m2", "m2"),
    "androidx.compose.material3": ("extracted", "app-surface", "material3", "m3"),
    "androidx.compose.material3.adaptive": (
        "extracted",
        "app-surface",
        "adaptive",
        "m3",
    ),
    "androidx.compose.runtime": ("extracted", "app-surface", "runtime", None),
    "androidx.compose.ui": ("extracted", "app-surface", "ui", None),
    "androidx.constraintlayout": ("extracted", "app-surface", "constraintlayout", None),
    "androidx.lifecycle": ("extracted", "app-surface", "lifecycle", None),
    "androidx.navigation": ("extracted", "app-surface", "navigation", None),
    "androidx.navigation3": ("extracted", "app-surface", "navigation3", None),
    "androidx.navigationevent": ("extracted", "adjacent", "navigationevent", None),
    "androidx.paging": ("extracted", "app-surface", "paging", None),
    "androidx.savedstate": ("extracted", "adjacent", "savedstate", None),
    "androidx.window": ("extracted", "app-surface", "window", None),
}
"""The ratified closure: 16 groups, 14 app-surface, 2 adjacent.

Change only with a decision.
"""

COMPONENT_GROUPS = {
    "androidx.compose.animation",
    "androidx.compose.foundation",
    "androidx.compose.material3",
    "androidx.compose.material3.adaptive",
}
"""Groups whose public, Unit-returning composables are components (plan 31 step 1).

M2 is extracted but contributes none: design profiles are never merged
(ADR-0021).
"""

DOMAIN_OVERRIDES = {"icons", "tooling"}
"""Artifact domains that differ from the default domain of their group."""

DIGEST = re.compile(r"\A[0-9a-f]{64}\Z")
COORDINATE = re.compile(r"\A[^:\s]+:[^:\s]+:[^:\s]+\Z")


@pytest.fixture(scope="module")
def closure() -> dict[str, Any]:
    """The parsed closure document."""
    return json.loads(CLOSURE_PATH.read_text(encoding="utf-8"))


def test_the_ratified_groups_and_nothing_else(closure: dict[str, Any]) -> None:
    assert closure["schema"] == 1
    assert set(closure["groups"]) == set(GROUPS)


def test_every_group_keeps_its_ratified_classification(
    closure: dict[str, Any],
) -> None:
    for name, (status, category, domain, design) in GROUPS.items():
        group = closure["groups"][name]
        assert group["status"] == status, name
        assert group["category"] == category, name
        assert group["domain"] == domain, name
        assert group.get("design") == design, name


def test_only_the_ratified_groups_contribute_components(
    closure: dict[str, Any],
) -> None:
    flagged = {
        name for name, group in closure["groups"].items() if group.get("components")
    }
    assert flagged == COMPONENT_GROUPS


def test_artifacts_are_well_formed_and_classified(closure: dict[str, Any]) -> None:
    groups = closure["groups"]
    seen: set[str] = set()
    for artifact in closure["artifacts"]:
        coordinate = artifact["coordinate"]
        assert COORDINATE.match(coordinate), coordinate
        group_name = coordinate.split(":", 1)[0]
        assert group_name in groups, coordinate
        assert coordinate not in seen, coordinate
        seen.add(coordinate)
        assert DIGEST.match(artifact["sha256"]), coordinate
        domain = artifact["domain"]
        assert (
            domain == groups[group_name]["domain"] or domain in DOMAIN_OVERRIDES
        ), coordinate


def test_pending_groups_are_empty_and_extracted_groups_are_not(
    closure: dict[str, Any],
) -> None:
    by_group: dict[str, list[dict[str, Any]]] = {name: [] for name in closure["groups"]}
    for artifact in closure["artifacts"]:
        by_group[artifact["coordinate"].split(":", 1)[0]].append(artifact)
    for name, group in closure["groups"].items():
        if group["status"] == "extracted":
            assert by_group[name], f"extracted group {name} lists no artifacts"
        else:
            assert not by_group[name], f"pending group {name} lists artifacts"


def test_the_gradle_task_consumes_the_closure_file() -> None:
    script = (EXTRACTOR / "build.gradle.kts").read_text(encoding="utf-8") + (
        EXTRACTOR / "src/main/kotlin/Inventory.kt"
    ).read_text(encoding="utf-8")
    assert "compose-closure.json" in script
    assert "composeToolingClasspath" in script
    assert "closure.support" in script
    assert 'startsWith("androidx.compose")' not in script


def test_the_file_is_sorted_for_stable_diffs(closure: dict[str, Any]) -> None:
    coordinates = [artifact["coordinate"] for artifact in closure["artifacts"]]
    assert coordinates == sorted(coordinates)
    assert list(closure["groups"]) == sorted(closure["groups"])


def test_tooling_is_pinned_and_never_extracted(closure: dict[str, Any]) -> None:
    artifacts = {artifact["coordinate"] for artifact in closure["artifacts"]}
    tooling = closure["tooling"]
    assert tooling, "tooling artifacts are part of the closure"
    seen: set[str] = set()
    for entry in tooling:
        coordinate = entry["coordinate"]
        assert COORDINATE.match(coordinate), coordinate
        assert DIGEST.match(entry["sha256"]), coordinate
        assert entry["domain"] == "tooling", coordinate
        assert coordinate not in artifacts, coordinate
        assert coordinate not in seen, coordinate
        seen.add(coordinate)
    coordinates = [entry["coordinate"] for entry in tooling]
    assert coordinates == sorted(coordinates)


def test_support_is_pinned_and_never_scanned(closure: dict[str, Any]) -> None:
    """Support artifacts resolve inside extracted groups without Android surface."""
    artifacts = {artifact["coordinate"] for artifact in closure["artifacts"]}
    tooling = {entry["coordinate"] for entry in closure["tooling"]}
    support = closure["support"]
    assert (
        support
    ), "JVM support inside extracted groups is pinned, not silently ignored"
    seen: set[str] = set()
    for entry in support:
        coordinate = entry["coordinate"]
        assert COORDINATE.match(coordinate), coordinate
        assert DIGEST.match(entry["sha256"]), coordinate
        group_name = coordinate.split(":", 1)[0]
        assert group_name in closure["groups"], coordinate
        assert closure["groups"][group_name]["status"] == "extracted", coordinate
        assert coordinate not in artifacts, coordinate
        assert coordinate not in tooling, coordinate
        assert coordinate not in seen, coordinate
        assert entry["reason"].strip(), coordinate
        seen.add(coordinate)
    coordinates = [entry["coordinate"] for entry in support]
    assert coordinates == sorted(coordinates)


@pytest.mark.skipif(
    not INVENTORY_PATH.exists(), reason="no local dumpComposeApi inventory"
)
def test_the_inventory_matches_the_closure(closure: dict[str, Any]) -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    scanned = {
        artifact["coordinate"]: artifact["sha256"]
        for artifact in inventory["artifacts"]
    }
    expected = {
        artifact["coordinate"]: artifact["sha256"] for artifact in closure["artifacts"]
    }
    assert scanned == expected
    assert not set(scanned) & {entry["coordinate"] for entry in closure["tooling"]}
    assert not set(scanned) & {entry["coordinate"] for entry in closure["support"]}
