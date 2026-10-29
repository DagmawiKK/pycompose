"""Moving to a new Compose BOM regenerates what follows from the pin (step 10)."""

from __future__ import annotations

import pytest
from pycompose_codegen.derive.upgrade import UpgradeError, manual, refresh_closure

CLOSURE = {
    "groups": {
        "androidx.compose.ui": {"domain": "ui"},
        "androidx.lifecycle": {"domain": "lifecycle"},
    },
    "artifacts": [
        {
            "coordinate": "androidx.compose.ui:ui-android:1.0",
            "sha256": "a",
            "domain": "ui",
        },
        {
            "coordinate": "androidx.compose.ui:ui-util-android:1.0",
            "sha256": "b",
            "domain": "icons",
        },
    ],
    "tooling": [
        {"coordinate": "androidx.compose.ui:ui-test-manifest:1.0", "sha256": "t"}
    ],
    "support": [
        {
            "coordinate": "androidx.lifecycle:lifecycle-common-jvm:2.0",
            "sha256": "s",
            "reason": "JVM support jar",
        }
    ],
}


def _resolved(*conflicts: dict[str, str]) -> dict[str, object]:
    return {
        "bom": "2",
        "artifacts": [
            {"coordinate": "androidx.compose.ui:ui-android:1.1", "sha256": "A"},
            {"coordinate": "androidx.compose.ui:ui-util-android:1.1", "sha256": "B"},
            {"coordinate": "androidx.compose.ui:ui-text-android:1.1", "sha256": "C"},
            # Tooling also resolves on the app classpath; it is pinned apart.
            {"coordinate": "androidx.compose.ui:ui-test-manifest:1.1", "sha256": "T"},
            {
                "coordinate": "androidx.lifecycle:lifecycle-common-jvm:2.1",
                "sha256": "S",
            },
        ],
        "tooling": [
            {"coordinate": "androidx.compose.ui:ui-test-manifest:1.1", "sha256": "T"}
        ],
        "conflicts": list(conflicts),
    }


def test_the_closure_takes_the_new_evidence_and_keeps_its_decisions() -> None:
    refreshed = refresh_closure(CLOSURE, _resolved())
    assert refreshed["groups"] == CLOSURE["groups"]
    assert refreshed["artifacts"] == [
        {
            "coordinate": "androidx.compose.ui:ui-android:1.1",
            "sha256": "A",
            "domain": "ui",
        },
        # A module keeps the domain it had, a new one takes its group's.
        {
            "coordinate": "androidx.compose.ui:ui-util-android:1.1",
            "sha256": "B",
            "domain": "icons",
        },
        {
            "coordinate": "androidx.compose.ui:ui-text-android:1.1",
            "sha256": "C",
            "domain": "ui",
        },
    ]
    assert refreshed["tooling"] == [
        {
            "coordinate": "androidx.compose.ui:ui-test-manifest:1.1",
            "sha256": "T",
            "domain": "tooling",
        }
    ]
    assert refreshed["support"] == [
        {
            "coordinate": "androidx.lifecycle:lifecycle-common-jvm:2.1",
            "sha256": "S",
            "reason": "JVM support jar",
        }
    ]


def test_a_module_moved_off_the_new_bom_stops_the_upgrade() -> None:
    moved = {"module": "androidx.compose.ui:ui", "resolved": "3", "bom": "2"}
    with pytest.raises(UpgradeError, match="moved off the new BOM"):
        refresh_closure(CLOSURE, _resolved(moved))


def test_hand_written_components_are_the_ones_flagged() -> None:
    lock = {
        "components": {
            "Text": {"wrapper": "ResourceText"},
            "Search": {"adapter": "manual"},
            "Button": {},
        }
    }
    assert manual(lock, {"Crossfade"}) == {"Text", "Search", "Crossfade"}


def test_a_decision_names_a_declaration_and_the_lock_stamps_the_pin() -> None:
    from pycompose_codegen.derive.component_binding import spell, stamped, unversioned

    source = {
        "artifact": "androidx.compose.ui:ui-android:1.0",
        "owner": "androidx.compose.ui.TextKt",
        "jvmName": "Text",
        "descriptor": "()V",
    }
    # A BOM change does not change what a decision names.
    assert spell(source) == spell(
        {**source, "artifact": "androidx.compose.ui:ui-android:2.0"}
    )
    assert unversioned(source)["artifact"] == "androidx.compose.ui:ui-android"
    pinned = stamped(unversioned(source), ["androidx.compose.ui:ui-android:2.0"])
    assert pinned["artifact"] == "androidx.compose.ui:ui-android:2.0"
