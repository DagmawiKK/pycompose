"""Every generated artifact obeys the bounded grammar the generator promises.

History: value specs were once emitted as an unbounded `+` chain, and Kotlin
resolves each link as a call on the previous result, so a large contract
overflowed the compiler's stack (fixed and regression-refused in
``tests/test_value_codegen.py``). These bounds generalize that lesson to every
artifact the generator renders. The artifact set comes from the generator
itself, so a new code-producing target cannot escape the bounds unnoticed.
"""

from __future__ import annotations

from pathlib import Path

from pycompose.schema.codegen.main import framework_artifacts, load_registry

MAX_LINE = 300
"""Widest generated line; today's widest is a 272-character table row."""

MAX_NESTING = 12
"""Deepest Kotlin bracket nesting; today's generated max is 6."""


def _code_artifacts() -> list[tuple[Path, str]]:
    """The generator's own .py/.kt emission, straight from the artifact table."""
    code = [
        (path, content)
        for path, content in framework_artifacts(load_registry()).items()
        if path.suffix in {".py", ".kt"}
    ]
    assert len(code) >= 8, "the bounds must actually see generated code"
    return code


def test_generated_code_never_chains_string_literals_with_a_plus_operator() -> None:
    """A `+` chain is one recursive call per link; links overflow the stack."""
    for path, text in _code_artifacts():
        lines = [line.rstrip() for line in text.split("\n")]
        offenses = [i for i, line in enumerate(lines) if '" +' in line]
        assert not offenses, f"{path}: `+`-joined literals at lines {offenses[:4]}"


def test_generated_lines_stay_bounded_in_width() -> None:
    """One-line table rows may be wide, but a runaway emitter must not hide."""
    for path, text in _code_artifacts():
        long = [line for line in text.split("\n") if len(line) > MAX_LINE]
        assert not long, f"{path}: {len(long)} line(s) over {MAX_LINE} characters"


def _kotlin_metadata_depth(text: str) -> int:
    """Bracket nesting depth of Kotlin code, skipping string contents."""
    depth = max_depth = 0
    in_string = False
    previous = ""
    for character in text:
        if in_string:
            if character == '"' and previous != "\\":
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "([{":
            depth += 1
            max_depth = max(max_depth, depth)
        elif character in ")]}":
            depth -= 1
        previous = character
    return max_depth


def test_generated_kotlin_stays_bounded_in_nesting() -> None:
    """Deep nesting in generated sources means the emitter grew a shape."""
    for path, text in _code_artifacts():
        if path.suffix != ".kt":
            continue
        depth = _kotlin_metadata_depth(text)
        assert depth <= MAX_NESTING, f"{path}: nesting reached {depth} > {MAX_NESTING}"
