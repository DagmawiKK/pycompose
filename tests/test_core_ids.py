"""core.ids: deterministic parent-path ids and collision detection."""

from __future__ import annotations

import pytest

from pycompose.core.ids import ROOT_ID, IdRegistry, child_id, id_path, make_path_id
from pycompose.errors import IrError


def test_root_id_constant() -> None:
    assert ROOT_ID == "root"


def test_child_ids_are_deterministic() -> None:
    first = child_id(child_id(ROOT_ID, 0), 1)
    second = child_id(child_id(ROOT_ID, 0), 1)
    assert first == second == "root.0.1"


def test_id_path_round_trips() -> None:
    assert id_path("root.0.1") == ("root", "0", "1")


def test_make_path_id_rejects_empty() -> None:
    with pytest.raises(IrError):
        make_path_id(())


def test_generated_ids_are_unique_across_a_tree() -> None:
    ids = [child_id(ROOT_ID, index) for index in range(100)]
    assert len(set(ids)) == len(ids)


def test_registry_detects_collision_with_context() -> None:
    registry = IdRegistry()
    registry.claim("root.0", node_type="Text", path=("root", "0"))
    with pytest.raises(IrError) as excinfo:
        registry.claim("root.0", node_type="Column", path=("root", "0"))
    message = str(excinfo.value)
    assert "node_id='root.0'" in message
    assert "node_type='Column'" in message
    assert "path=('root', '0')" in message


def test_registry_defaults_path_from_id() -> None:
    registry = IdRegistry()
    registry.claim("root.0", node_type="Text")
    assert "root.0" in registry
    assert "root.1" not in registry
    assert len(registry) == 1
