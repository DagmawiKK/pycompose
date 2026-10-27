"""pycompose check finds what a build or the store would refuse (§18.7, §21.7)."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from pycompose.cli.check import Problem, check, config_problems, play_problems

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = """<manifest xmlns:android="http://schemas.android.com/apk/res/android">
  <application>{}</application>
</manifest>"""


def _notes(tmp_path: Path) -> Path:
    target = tmp_path / "notes"
    shutil.copytree(
        ROOT / "examples/notes", target, ignore=shutil.ignore_patterns(".pycompose")
    )
    return target


def test_the_notes_app_checks_clean(tmp_path: Path) -> None:
    assert check(_notes(tmp_path), today=date(2026, 10, 24)) == []


def test_a_config_mistake_names_the_key_and_its_fix() -> None:
    problems = config_problems(
        {
            "app": {"name": "x", "application_id": "nodots", "version_name": "1"},
            "python": {"entrypoint": "main:app", "colour": "red"},
            "toolchain": {"schema_version": "1.23.0"},
        }
    )
    assert [p.where for p in problems] == [
        "app.version_code",
        "app.application_id",
        "python.colour",
    ]
    assert "reverse domain name" in problems[1].fix
    assert "known keys" in problems[2].fix


def test_an_app_that_fails_to_compose_is_reported(tmp_path: Path) -> None:
    root = _notes(tmp_path)
    (root / "app/main.py").write_text("raise RuntimeError('broken on import')\n")
    problems = check(root, today=date(2026, 10, 24))
    assert [p.where for p in problems] == ["app"]
    assert "broken on import" in problems[0].message


def test_play_policy_reads_the_deadline_and_the_manifest() -> None:
    exported = '<receiver android:name=".Hook" android:exported="true" />'
    problems = play_problems(MANIFEST.format(exported), date(2026, 10, 24))
    assert problems == [
        Problem(
            "receiver .Hook",
            "is exported without a permission",
            "guard it with android:permission or stop exporting it",
        )
    ]
    # Before a deadline, a lower target is still accepted.
    assert play_problems(MANIFEST.format(""), date(2025, 1, 1)) == []


GOLDEN = """
[app]
name = "Golden"
application_id = "com.example.golden"
version_name = "1.0.0"
version_code = 3
icon = "icon.svg"
icon_background = "#123456"

[python]
entrypoint = "main:app"
source_dir = "app"
requirements = ["attrs==24.2.0"]

[resources]
path = "resources"

[theme]
colors = "theme.json"
dynamic = false
dark = "system"

[theme.fonts]
display = "fraunces"
body = "inter"

[theme.shapes]
extra_small = 4
small = 8
medium = 12
large = 16
extra_large = 28

[signing]
keystore = "release.jks"
key_alias = "upload"
store_password_env = "STORE"
key_password_env = "KEY"

[android]
permissions = ["android.permission.INTERNET"]
plugins = []

[extensions]
definitions = []

[toolchain]
library_version = "0.1.0"
schema_version = "1.23.0"
template_version = "0.7.1"
android_dir = ".pycompose/android"
"""


def _keys(schema: dict, prefix: str = "") -> set[str]:
    found = set()
    for name, spec in schema.get("properties", {}).items():
        path = f"{prefix}.{name}".lstrip(".")
        found |= _keys(spec, path) if spec.get("type") == "object" else {path}
    return found


def _used(config: dict, prefix: str = "") -> set[str]:
    found = set()
    for name, value in config.items():
        path = f"{prefix}.{name}".lstrip(".")
        found |= _used(value, path) if isinstance(value, dict) else {path}
    return found


def test_a_boolean_key_must_be_true_or_false() -> None:
    problems = config_problems({"theme": {"dynamic": "yes"}})
    assert ("theme.dynamic", "must be a boolean") in {
        (problem.where, problem.message) for problem in problems
    }


def test_every_schema_key_is_exercised_by_a_golden_config() -> None:
    import json
    import tomllib
    from importlib.resources import files

    schema = json.loads(
        files("pycompose").joinpath("schema", "pycompose.schema.json").read_text()
    )
    golden = tomllib.loads(GOLDEN)
    assert config_problems(golden) == []
    assert _keys(schema) == _used(golden)


def test_a_component_the_build_would_generate_checks_clean(tmp_path: Path) -> None:
    from test_cli_init import cli

    assert cli(tmp_path, "init", "demo").returncode == 0
    main = tmp_path / "demo" / "app" / "main.py"
    main.write_text(
        main.read_text()
        .replace(
            "from m3 import Text", "from m3 import Column, HorizontalDivider, Text"
        )
        .replace(
            'return Text(id="greeting", text="Hello PyCompose")',
            'return Column(children=[Text(text="Hello"), HorizontalDivider()])',
        )
        .replace("-> Text:", "-> Column:")
    )
    assert check(tmp_path / "demo", today=date(2026, 10, 24)) == []
