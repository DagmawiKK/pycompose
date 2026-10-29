"""A holder's drive table names one pinned member per anchor, or refuses it."""

from types import SimpleNamespace

from pycompose_codegen.derive.holders import _table

VALUE = "pkg.Value"
FOUND = SimpleNamespace(
    classes=[
        SimpleNamespace(classifier=VALUE, document={"enumEntries": ["Open", "Closed"]})
    ]
)
ANCHOR = SimpleNamespace(type=SimpleNamespace(classifier="pkg/Value"))
ANIMATE = "androidx.compose.foundation.gestures.animateTo"


def _member(name: str, *, takes_anchor: bool = False) -> SimpleNamespace:
    return SimpleNamespace(name=name, parameters=[ANCHOR] if takes_anchor else [])


def _constant(entry: str) -> dict[str, str]:
    return {"kind": "constant", "anchor": f"{VALUE}.{entry}", "callee": ANIMATE}


def test_constant_members_win_and_snapping_parameters_are_ignored() -> None:
    evidence = [
        (_member("open"), _constant("Open")),
        (
            _member("animateTo", takes_anchor=True),
            {"kind": "parameter", "callee": ANIMATE},
        ),
        (
            _member("snapTo", takes_anchor=True),
            {"kind": "parameter", "callee": "snapTo"},
        ),
    ]
    value, table, missing = _table(FOUND, evidence)  # type: ignore[arg-type]
    assert (value, missing) == (VALUE, [])
    assert {entry: d.name for entry, d in table.items()} == {
        "Open": "open",
        "Closed": "animateTo",
    }


def test_an_ambiguous_or_uncovered_anchor_is_refused_by_name() -> None:
    evidence = [
        (_member("open"), _constant("Open")),
        (_member("show"), _constant("Open")),
    ]
    _, table, missing = _table(FOUND, evidence)  # type: ignore[arg-type]
    assert table == {}
    assert missing == ["Open", "Closed"]
