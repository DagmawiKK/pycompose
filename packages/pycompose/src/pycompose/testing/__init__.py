"""Moved: the test driver is its own distribution, pycompose-testing.

It runs on a developer's machine, never on a device, so the runtime no longer
carries it (ADR-0063). Importing the old name says where it went.
"""

raise ImportError(
    "pycompose.testing moved to pycompose_testing: install pycompose-testing "
    "(or pycompose[testing]) and import from pycompose_testing"
)
