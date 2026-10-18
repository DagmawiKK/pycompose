"""SQLite reference extension: no ORM, SQL wrapper or thread-check bypass."""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

from pycompose.extensions import Resource


def database(
    path: Path | str, *, timeout: float = 5.0, capacity: int = 16
) -> Resource[sqlite3.Connection]:
    """Open, query and close a normal SQLite connection on one owned thread.

    Operations keep ordinary ``with connection:`` transactions, parameterized
    SQL, cursors and row factories. Migrations/cache policy belong to the app.

    Args:
        path: Explicit private database filename, or SQLite's :memory: name.
        timeout: Finite positive lock wait in seconds.
        capacity: Bound on admitted operations and unacknowledged outcomes.

    Returns:
        A serial resource retaining SQLite's default thread-affinity checks.

    Raises:
        ValueError: If the timeout is not finite and positive.
    """
    if type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    return Resource(
        lambda: sqlite3.connect(path, timeout=timeout),
        close=lambda connection: connection.close(),
        workers=1,
        capacity=capacity,
    )
