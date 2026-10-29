"""pycompose.storage — what an app keeps on the device.

``paths`` names the app's private folders, ``documents`` stores typed data
atomically outside the saved-state budget, and ``media`` saves the images an
app shows from files. None of it needs Android: the host hands the folders over
as plain paths.
"""

from pycompose.storage.documents import (
    Document,
    Repository,
    diagnostics,
    root,
    use_root,
)
from pycompose.storage.media import MEDIA, image
from pycompose.storage.paths import AppPaths, paths

__all__ = [
    "MEDIA",
    "AppPaths",
    "Document",
    "Repository",
    "diagnostics",
    "image",
    "paths",
    "root",
    "use_root",
]
