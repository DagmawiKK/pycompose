"""Embedded catalog JSON is cut by content, so one new entry is a small diff."""

from __future__ import annotations

import difflib
import json

from pycompose.codegen.literals import CHUNK_MAX, chunks
from pycompose.compiler.lock import LOCK

RAW = json.dumps(json.loads(LOCK.read_text()), separators=(",", ":"), sort_keys=True)


def test_the_chunks_join_back_within_the_width() -> None:
    cut = chunks(RAW)
    assert "".join(cut) == RAW
    assert max(map(len, cut)) <= CHUNK_MAX


def test_an_inserted_entry_rewrites_only_the_chunks_around_it() -> None:
    # Fixed-width slices shifted every line after an insertion: thousands of
    # committed lines changed for one new modifier.
    before = chunks(RAW)
    after = chunks(RAW.replace('"modifiers":{', '"modifiers":{"zzz":{"props":{}},', 1))
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    changed = sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    )
    assert changed <= 10
