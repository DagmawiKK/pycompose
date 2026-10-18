"""Reusable public conformance for resource recipes; never staged into apps.

Subclass this mixin in a pytest Test class and implement open_resource, operation
and expected. Passing proves these lifecycle contracts only, not Android package
compatibility or arbitrary thread-safety of the selected library.
"""

from __future__ import annotations

import threading
from typing import Generic, TypeVar
from unittest import TestCase

from pycompose.errors import StateError
from pycompose.extensions import Resource

T = TypeVar("T")


class ResourceContract(Generic[T]):
    """Library-neutral lifecycle tests for independently packaged contributors."""

    expected: object

    def open_resource(self, *, capacity: int = 16) -> Resource[T]:
        """Create the recipe under test with a configurable admission bound.

        Args:
            capacity: Maximum physical work and unacknowledged outcomes.

        Returns:
            A newly owned resource; never a process-global singleton.

        Raises:
            NotImplementedError: Until the contributor supplies a recipe.
        """
        raise NotImplementedError

    def operation(self, value: T) -> object:
        """Perform a real deterministic operation using the ordinary library.

        Args:
            value: The library resource on its owning execution lane.

        Returns:
            A result independently comparable to expected.

        Raises:
            NotImplementedError: Until the contributor supplies an operation.
        """
        raise NotImplementedError

    def test_roundtrip_and_close(self) -> None:
        """Check repeated use, idempotent cleanup and rejection after disposal."""
        check = TestCase()
        resource = self.open_resource()
        try:
            for _ in range(2):
                check.assertEqual(
                    resource.submit(self.operation).result(5), self.expected
                )
        finally:
            cleanup = resource.close()
            cleanup.result(5)
        check.assertIs(resource.close(), cleanup)
        with check.assertRaises(StateError):
            resource.submit(self.operation)

    def test_cancelled_work_retains_physical_capacity(self) -> None:
        """Check cancellation-interest does not imply termination or free capacity."""
        check = TestCase()
        entered, release = threading.Event(), threading.Event()
        resource = self.open_resource(capacity=1)

        def delayed(value: T) -> object:
            entered.set()
            check.assertTrue(release.wait(5), "conformance gate timed out")
            return self.operation(value)

        try:
            task = resource.submit(delayed)
            check.assertTrue(entered.wait(5), "operation never started")
            task.cancel()
            with check.assertRaises(StateError):
                resource.submit(self.operation)
            release.set()
            check.assertEqual(task.result(5), self.expected)
        finally:
            release.set()
            resource.close().result(5)
