"""The component catalog the runtime validates against, loaded once.

The catalog is ``catalog.lock.json``, shipped beside this module as package
data. Loading it here, rather than embedding it in generated source, keeps a
single copy of the catalog in the repository: the committed lock.
"""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Any

from pycompose.contract.registry_rules import with_rules
from pycompose.contract.registry_types import Registry
from pycompose.contract.version import version_parts

__all__ = [
    "KNOWN_ACTION_IDS",
    "MIN_LIBRARY_VERSION",
    "MIN_SCHEMA_VERSION",
    "REGISTRY",
    "SCHEMA_VERSION",
    "lock",
]


@cache
def lock() -> dict[str, Any]:
    """Return the shipped catalog lock exactly as committed.

    Returns:
        The parsed lock; callers must not mutate it.
    """
    text = files("pycompose.contract").joinpath("catalog.lock.json").read_text("utf-8")
    loaded: dict[str, Any] = json.loads(text)
    return loaded


def _runtime() -> dict[str, Any]:
    return with_rules(json.loads(json.dumps(lock())))


_CATALOG = _runtime()

SCHEMA_VERSION: str = _CATALOG["schemaVersion"]
MIN_SCHEMA_VERSION: str = min(
    _CATALOG.get("supportedSchemaVersions", [SCHEMA_VERSION]), key=version_parts
)
MIN_LIBRARY_VERSION: str = _CATALOG["minLibraryVersion"]
KNOWN_ACTION_IDS: tuple[str, ...] = tuple(sorted(_CATALOG.get("actions", {})))
REGISTRY: Registry = Registry.from_mapping(_CATALOG)
