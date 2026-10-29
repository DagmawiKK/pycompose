"""pycompose.runtime — the one owner of time, tasks and threads.

Everything nondeterministic the runtime does goes through here: reading the
clock, drawing randomness, starting tasks and running work on threads. The
rest of the runtime asks this package and never the standard library
directly, so a test can swap the real implementation for a deterministic one.
"""

from pycompose.runtime.scope import Scope

__all__ = ["Scope"]
