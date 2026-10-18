"""The template is what ``pycompose init`` scaffolds, so it must match the modules.

``gen.py`` mirrors every template file that has a counterpart in ``android/``, but
nothing failed when a *new* framework source was added to the modules and not to
the template: a generated app would then receive a renderer from before the
feature it renders, and the mistake would surface as an unresolved reference in
somebody's project rather than here.
"""

from __future__ import annotations

from pathlib import Path

from tools.template.sync import is_excluded

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "pycompose/templates/android"
ANDROID = ROOT / "android"
MODULES = ("ir", "renderer", "host")


def test_every_framework_source_is_carried_by_the_template() -> None:
    """A module source the template lacks is a file generated apps never get."""
    for module in MODULES:
        source_root = ANDROID / module / "src/main"
        for path in sorted(source_root.rglob("*")):
            if not path.is_file() or is_excluded(path.relative_to(source_root)):
                continue
            counterpart = TEMPLATE / module / "src/main" / path.relative_to(source_root)
            assert counterpart.is_file(), (
                f"{path.relative_to(ANDROID)} has no template counterpart; "
                "`pycompose init` would scaffold a project without it"
            )


def test_the_template_matches_the_modules_byte_for_byte() -> None:
    """A drifted copy ships a project that does not match the code it came from.

    Bytes, not text: the Gradle wrapper jar and ``gradlew.bat``'s line endings
    are part of what ``pycompose init`` writes, and neither survives a text
    round trip.
    """
    for path in sorted(TEMPLATE.rglob("*")):
        if not path.is_file():
            continue
        source = ANDROID / path.relative_to(TEMPLATE)
        if not source.is_file():
            continue
        assert source.read_bytes() == path.read_bytes(), (
            f"{path.relative_to(TEMPLATE)} differs from {source.relative_to(ROOT)}; "
            "run python tools/schema/gen.py"
        )


def test_planning_modules_are_excluded_from_the_packaged_runtime() -> None:
    """Metadata and evidence tooling must never ship inside an application.

    An APK that carried the planner would expose the whole definition and
    evidence format to an app that only ever produces outcomes, and would grow
    every build by tooling it never calls.
    """
    gradle = (TEMPLATE / "host/build.gradle.kts").read_text(encoding="utf-8")

    for module in ("definition.py", "evidence.py"):
        assert (
            f"pycompose/extensions/{module}" in gradle
        ), f"pycompose/extensions/{module} would be packaged into every APK"
