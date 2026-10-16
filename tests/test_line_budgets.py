"""File growth is governed like every other contract: budgeted and checked."""

from __future__ import annotations

from pathlib import Path

from limits import BUDGETS, DEFAULT_LIMIT, check

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
