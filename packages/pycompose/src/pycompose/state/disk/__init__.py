"""pycompose.state.disk — what an app keeps on the device.

``paths`` names the app's private folders, ``documents`` stores typed data
atomically outside the saved-state budget, and ``media`` saves the images an
app shows from files. None of it needs Android: the host hands the folders over
as plain paths.
"""

from pycompose.state.disk.documents import (
    Document,
    Repository,
    diagnostics,
    documents_root,
    use_root,
)
from pycompose.state.disk.media import MEDIA, image
from pycompose.state.disk.paths import AppPaths, paths

__all__ = [
    "MEDIA",
    "AppPaths",
    "Document",
    "Repository",
    "diagnostics",
    "image",
    "paths",
    "documents_root",
    "use_root",
]
