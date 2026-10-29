"""File growth is governed like every other contract: budgeted and checked."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.limits import (
    BUDGETS,
    DEFAULT_LIMIT,
    PACKAGE_FILES,
    check,
    growth,
    packages,
)

ROOT = Path(__file__).resolve().parents[1]


def test_hand_editable_files_stay_within_their_budgets() -> None:
    """Over budget means split by responsibility, never silence the check."""
    violations = check(ROOT)
    report = "\n".join(
        f"{path}: {lines} > {limit}" for path, lines, limit in violations
    )
    assert not violations, report


def test_the_budget_table_covers_its_own_alphabet() -> None:
    """Budgets are closed data: every value is a positive integer."""
    assert DEFAULT_LIMIT > 0
    assert all(limit > 0 for limit in BUDGETS.values())


def _repository(root: Path, files: dict[str, int]) -> None:
    """A git checkout holding ``files``, each that many lines, committed."""
    for name, lines in files.items():
        (root / name).write_text("x = 1\n" * lines)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    author = ["-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(
        ["git", "-C", str(root), *author, "commit", "-qm", "base"], check=True
    )


def test_a_file_near_its_budget_may_grow_only_a_little_in_one_change(
    tmp_path: Path,
) -> None:
    _repository(tmp_path, {"near.py": 400, "far.py": 100})
    (tmp_path / "near.py").write_text("x = 1\n" * 450)
    (tmp_path / "far.py").write_text("x = 1\n" * 200)
    # far.py doubled, but it is far from its budget: ordinary work.
    assert growth(tmp_path, "HEAD") == [(tmp_path / "near.py", 400, 450)]


def test_a_file_with_its_own_budget_was_reviewed_and_may_grow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repository(tmp_path, {"near.py": 400})
    (tmp_path / "near.py").write_text("x = 1\n" * 450)
    monkeypatch.setitem(BUDGETS, "near.py", 700)
    assert growth(tmp_path, "HEAD") == []


def test_growth_from_an_unreadable_base_is_reported_not_guessed(
    tmp_path: Path,
) -> None:
    _repository(tmp_path, {"near.py": 400})
    assert growth(tmp_path, "no-such-revision") is None


def test_a_directory_past_its_file_count_is_noted(tmp_path: Path) -> None:
    _repository(tmp_path, {f"m{index}.py": 1 for index in range(PACKAGE_FILES + 1)})
    assert packages(tmp_path) == [(tmp_path, PACKAGE_FILES + 1, PACKAGE_FILES + 1)]
