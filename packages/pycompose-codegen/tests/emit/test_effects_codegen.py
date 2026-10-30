"""Every effect the catalog declares is typed, and documented, on both sides."""

from __future__ import annotations

import json
from pathlib import Path

from pycompose_codegen.emit.effects import render_kotlin_effects, render_python_effects

LOCK = json.loads(
    (Path(__file__).resolve().parents[4] / "schema" / "catalog.lock.json").read_text()
)
PYTHON = render_python_effects(LOCK)
KOTLIN = render_kotlin_effects(LOCK)


def test_every_effect_is_a_python_class_and_a_kotlin_case() -> None:
    for kind in LOCK["effects"]:
        name = kind[:1].upper() + kind[1:]
        assert f"class {name}(TypedEffect):" in PYTHON
        assert f'"{kind}" ->' in KOTLIN


def test_the_policys_words_document_both_sides() -> None:
    summary = LOCK["effects"]["toast"]["summary"]
    assert f'"""{summary}' in PYTHON
    assert f"/** {summary} */" in KOTLIN


def test_a_default_is_the_fields_default_on_both_sides() -> None:
    assert 'accept: str = "*/*"' in PYTHON
    assert '?.contentOrNull ?: "*/*"' in KOTLIN


def test_no_documentation_opens_or_closes_a_kotlin_comment() -> None:
    for line in KOTLIN.splitlines():
        if line.strip().startswith("/**"):
            body = line.strip()[3:-2]
            assert "/*" not in body and "*/" not in body, line
