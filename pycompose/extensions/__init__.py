"""Public coordination contracts for explicitly selected Python extensions.

No integration implementation is discovered or imported by this package.
"""

from pycompose.extensions.environment import AppPaths, paths
from pycompose.extensions.work import Resource, Task

__all__ = ["AppPaths", "Resource", "Task", "paths"]
