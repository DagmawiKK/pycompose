"""Media an app saves to show from a file: once, by content."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from pycompose.storage import media
from pycompose.storage.paths import install

# A one-pixel PNG.
PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.fixture(autouse=True)
def cache(tmp_path: Path) -> Path:
    install(str(tmp_path / "files"), str(tmp_path / "cache"))
    yield tmp_path / "cache"
    install()


def test_the_same_bytes_are_saved_once_under_their_digest(cache: Path) -> None:
    first = media.image(PIXEL)
    assert first == media.image(bytearray(PIXEL))
    (saved,) = (cache / media.MEDIA).iterdir()
    assert first == f"@file/{saved.name}"
    assert saved.read_bytes() == PIXEL


def test_a_path_or_anything_that_saves_itself_is_an_image(tmp_path: Path) -> None:
    path = tmp_path / "pixel.png"
    path.write_bytes(PIXEL)

    class Picture:
        def save(self, file: object, format: str) -> None:
            assert format == "PNG"
            file.write(PIXEL)  # type: ignore[attr-defined]

    assert media.image(path) == media.image(str(path)) == media.image(Picture())


def test_bytes_that_are_no_image_are_refused() -> None:
    with pytest.raises(ValueError, match="PNG, JPEG"):
        media.image(b"not a picture")


def test_a_file_already_in_the_cache_is_not_read_again(cache: Path) -> None:
    reference = media.image(PIXEL)
    saved = cache / media.MEDIA / reference.removeprefix("@file/")
    saved.write_bytes(b"changed underneath")  # proves it is not read
    assert media.image(saved) == reference
