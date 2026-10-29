"""Split into :mod:`pycompose.foundation` and :mod:`pycompose.material3`.

This name works for one release.
"""

from pycompose._moved import forward

forward(__name__, ("pycompose.foundation", "pycompose.material3"), globals())
