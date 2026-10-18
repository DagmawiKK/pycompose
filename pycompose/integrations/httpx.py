"""HTTPX reference extension, using only the public resource interface."""

from __future__ import annotations

import math
from importlib import import_module
from typing import Any

from pycompose.extensions import Resource


def client(
    *, timeout: float = 10.0, workers: int = 4, capacity: int = 16, **options: Any
) -> Resource[Any]:
    """Own a synchronous HTTPX client without wrapping its request interface.

    HTTPX permits sharing a synchronous client across threads. AsyncClient is a
    different execution contract and is deliberately not enabled by this recipe.

    Args:
        timeout: Finite positive default timeout in seconds; individual calls
            retain HTTPX's ordinary explicit per-request timeout controls.
        workers: Concurrent client users on the bounded resource executor.
        capacity: Admitted operations including physically running obsolete work.
        **options: Ordinary HTTPX Client options; verification stays enabled by default.

    Returns:
        A resource whose operations receive the normal HTTPX Client.

    Raises:
        ValueError: If the default timeout is not finite and positive.
    """
    if type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    return Resource(
        lambda: import_module("httpx").Client(timeout=timeout, **options),
        close=lambda session: session.close(),
        workers=workers,
        capacity=capacity,
    )
