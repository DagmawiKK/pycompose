"""Picking files: the pick effect goes out, the host's answer comes back as a path."""

from __future__ import annotations

from pathlib import Path

from test_blocks import project, value
from test_media import PIXEL

from pycompose import media
from pycompose.extensions.environment import paths
from pycompose.testing.driver import AppDriver

PICKS = """
from pathlib import Path
import pycompose.blocks as pc

def size(photo):
    return f"{len(Path(photo).read_bytes())} bytes"

with pc.Blocks() as app:
    photo = pc.Image(label="Photo", interactive=True)
    weight = pc.Textbox(label="Weight")
    photo.change(size, photo, weight)
    paper = pc.File(label="Paper", accept="application/pdf")
    send = pc.UploadButton("Upload notes", accept="text/plain")
    named = pc.Textbox(label="Named")
    send.upload(lambda path: Path(path).name, send, named)
"""


def asked(app: AppDriver) -> dict[str, str]:
    """The last pick the app asked the host for."""
    picks = [e for e in app.effects if e["kind"] == "pickFile"]
    payload: dict[str, str] = picks[-1]["payload"]
    return payload


def test_a_picked_photo_shows_and_reaches_its_listeners(tmp_path: Path) -> None:
    with AppDriver(project(tmp_path / "picks", PICKS)) as app:
        app.click(text="Choose photo")
        request = asked(app)
        assert request["accept"] == "image/*"
        # The host copies the pick into the media cache, then answers.
        reference = media.image(PIXEL)
        saved = paths().cache / media.MEDIA / reference.removeprefix("@file/")
        app.lifecycle("onFilePicked", request=request["request"], path=str(saved))
        app.settle()
        images = [n["props"]["resource"] for n in app.nodes() if n["type"] == "Image"]
        assert images == [reference]
        assert value(app, "Weight") == f"{len(PIXEL)} bytes"
        assert "Change photo" in app.texts()


def test_a_cancelled_pick_changes_nothing(tmp_path: Path) -> None:
    with AppDriver(project(tmp_path / "picks", PICKS)) as app:
        app.click(text="Choose photo")
        app.lifecycle("onFilePicked", request=asked(app)["request"], path="")
        app.settle()
        assert not [n for n in app.nodes() if n["type"] == "Image"]
        assert value(app, "Weight") == ""


def test_a_pick_that_is_no_image_is_a_toast(tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("not a picture")
    with AppDriver(project(tmp_path / "picks", PICKS)) as app:
        app.click(text="Choose photo")
        app.lifecycle("onFilePicked", request=asked(app)["request"], path=str(notes))
        toasts = [e["payload"]["message"] for e in app.effects if e["kind"] == "toast"]
        assert toasts == ["an image must be PNG, JPEG, WebP or GIF"]


def test_files_and_uploads_hold_the_picked_path(tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("hello")
    with AppDriver(project(tmp_path / "picks", PICKS)) as app:
        assert "No file chosen" in app.texts()
        app.click(text="Choose file")
        assert asked(app)["accept"] == "application/pdf"
        app.lifecycle("onFilePicked", request=asked(app)["request"], path=str(notes))
        assert "notes.txt" in app.texts()
        app.click(text="Upload notes")
        assert asked(app)["accept"] == "text/plain"
        app.lifecycle("onFilePicked", request=asked(app)["request"], path=str(notes))
        app.settle()
        assert value(app, "Named") == "notes.txt"


PHOTOS = Path(__file__).resolve().parents[1] / "examples/photos"


def test_the_photo_example_edits_the_picked_photo(tmp_path: Path) -> None:
    from PIL import Image as Picture

    source = tmp_path / "wide.png"
    Picture.new("RGB", (40, 20), "orange").save(source)
    with AppDriver(PHOTOS) as app:
        app.click(text="Outline")  # a change before any photo shows nothing, quietly
        app.settle()
        app.click(text="Choose photo")
        saved = paths().cache / media.MEDIA / media.image(source).removeprefix("@file/")
        app.lifecycle("onFilePicked", request=asked(app)["request"], path=str(saved))
        app.settle()
        app.act("onValueChangeFinished", app.find(type="Slider"), value=90.0)
        app.click(text="Black and white")
        app.settle()
        assert not [e for e in app.effects if e["kind"] == "toast"]
        app.click(text="Details")
        details = '{\n  "width": 20,\n  "height": 40,\n  "look": "Black and white"\n}'
        assert details in app.texts()
