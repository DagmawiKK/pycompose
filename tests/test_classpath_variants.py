"""Android variant evidence at the public inventory reader boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_classpath_dump import declaration, write_inventory


def test_android_jvm_aar_retains_public_components(tmp_path: Path) -> None:
    from tools.schema.classpath_dump import inventory

    # Resolved Material 3 Android artifacts can advertise JVM rather than
    # androidJvm; the Android environment and AAR attributes prove the variant.
    document = write_inventory(tmp_path, [declaration()])
    document["artifacts"][0].update(
        variant="jvm",
        attributes={
            "artifactType": "aar",
            "org.gradle.category": "library",
            "org.gradle.jvm.environment": "android",
            "org.gradle.libraryelements": "aar",
            "org.gradle.usage": "java-api",
            "org.jetbrains.kotlin.platform.type": "jvm",
        },
    )
    (tmp_path / "inventory.json").write_text(json.dumps(document))
    assert [component.name for component in inventory(tmp_path).ui] == ["Text"]


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("org.gradle.jvm.environment", "standard-jvm"),
        ("artifactType", "jar"),
        ("org.gradle.libraryelements", "jar"),
        ("org.jetbrains.kotlin.platform.type", "native"),
        ("org.gradle.jvm.environment", None),
        ("artifactType", None),
        ("org.gradle.libraryelements", None),
        ("org.jetbrains.kotlin.platform.type", None),
    ],
)
def test_jvm_artifact_needs_complete_android_aar_evidence(
    tmp_path: Path, attribute: str, value: str | None
) -> None:
    from tools.schema.classpath_dump import inventory

    document = write_inventory(tmp_path, [declaration()])
    attributes = {
        "artifactType": "aar",
        "org.gradle.jvm.environment": "android",
        "org.gradle.libraryelements": "aar",
        "org.jetbrains.kotlin.platform.type": "jvm",
    }
    if value is None:
        del attributes[attribute]
    else:
        attributes[attribute] = value
    document["artifacts"][0].update(variant="jvm", attributes=attributes)
    (tmp_path / "inventory.json").write_text(json.dumps(document))
    with pytest.raises(ValueError, match="non-Android artifact"):
        inventory(tmp_path)


def test_unspecified_variant_cannot_supply_public_ui(tmp_path: Path) -> None:
    from tools.schema.classpath_dump import inventory

    document = write_inventory(tmp_path, [declaration()])
    document["artifacts"][0]["variant"] = None
    (tmp_path / "inventory.json").write_text(json.dumps(document))
    with pytest.raises(ValueError, match="a component requires an Android variant"):
        inventory(tmp_path)
