"""Media an app shows from files: written once, named by content.

The host shows only images it can read by name, from the app's own media cache;
it loads nothing from the network. An image from the web is downloaded by the
app and saved here; the reference this returns goes in any image prop.

Names are the content's SHA-256, so the same bytes are written once and a name
always means the same picture: the host may cache it forever.
"""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
from pathlib import Path
from typing import Any

from pycompose.model.nodes.resources import valid_resource
from pycompose.state.disk.paths import paths

__all__ = ["MEDIA", "image"]

MEDIA = "pycompose-media"
"""The folder in the app's cache the host reads media from."""

_FORMATS = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


def _format(data: bytes) -> str:
    """Name an image's format from its first bytes."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    for magic, name in _FORMATS:
        if data.startswith(magic):
            return name
    raise ValueError("an image must be PNG, JPEG, WebP or GIF")


def image(source: bytes | str | Path | Any) -> str:
    """Save an image to the app's media cache and return its reference.

    It blocks on the disk, so call it where blocking is fine: in an event's
    function, or on a pool through ``to_thread``.

    Args:
        source: The image's bytes, a path to its file, or anything with a
            ``save(file, format)`` method, such as a PIL image (saved as PNG).

    Returns:
        ``@file/<sha256>.<format>``, for an image prop. Bytes that are not
        a PNG, JPEG, WebP or GIF image raise ``ValueError``.
    """
    folder = paths().cache / MEDIA
    if isinstance(source, str | Path):
        path = Path(source)
        reference = f"@file/{path.name}"
        if path.parent == folder and valid_resource(reference, ("file",)):
            return reference  # already saved here, as a picked file is
        data = path.read_bytes()
    elif isinstance(source, bytes | bytearray | memoryview):
        data = bytes(source)
    else:
        buffer = io.BytesIO()
        source.save(buffer, "PNG")
        data = buffer.getvalue()
    name = f"{hashlib.sha256(data).hexdigest()}.{_format(data)}"
    target = folder / name
    if not target.exists():
        folder.mkdir(parents=True, exist_ok=True)
        # Written whole, then renamed: the host never reads half a picture.
        handle, partial = tempfile.mkstemp(dir=folder, suffix=".partial")
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        Path(partial).replace(target)
    return f"@file/{name}"
