"""Display components: pictures, labels and JSON written by events."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pycompose_testing.driver import AppDriver
from test_blocks import project
from test_media import PIXEL

import pycompose.blocks as pc

DISPLAY = f"""
import pycompose.blocks as pc

PIXEL = {PIXEL!r}
SEEN = []

def show():
    guess = {{"cat": 0.25, "dog": 0.7, "fox": 0.05}}
    return PIXEL, [PIXEL, PIXEL], guess, {{"ok": True}}

def look(picture, pictures):
    with open(picture, "rb") as f:
        SEEN.append((f.read() == PIXEL, len(pictures)))

with pc.Blocks() as app:
    picture = pc.Image(label="Picture")
    pictures = pc.Gallery(label="Pictures")
    guess = pc.Label(label="Guess", top=2)
    raw = pc.JSON(label="Raw")
    pc.Button("Show").click(show, outputs=[picture, pictures, guess, raw])
    pc.Button("Look").click(look, inputs=[picture, pictures])
"""


def test_pictures_labels_and_json_show_what_an_event_wrote(tmp_path: Path) -> None:
    with AppDriver(project(tmp_path / "display", DISPLAY)) as app:
        assert not [n for n in app.nodes() if n["type"] == "Image"]
        app.click(text="Show")
        app.settle()
        images = [n["props"]["resource"] for n in app.nodes() if n["type"] == "Image"]
        assert len(images) == 3 and len(set(images)) == 1
        assert images[0].startswith("@file/") and images[0].endswith(".png")
        scales = [
            n["props"]["contentScale"]["name"]
            for n in app.nodes()
            if n["type"] == "Image"
        ]
        assert scales == ["FillWidth", "Crop", "Crop"]
        texts = app.texts()
        assert "dog" in texts and "dog  70%" in texts and "cat  25%" in texts
        assert "fox  5%" not in texts
        assert json.dumps({"ok": True}, indent=2) in texts
        app.click(text="Look")
        app.settle()
        assert sys.modules["main"].SEEN == [(True, 2)]


def test_a_picture_reference_must_name_an_image() -> None:
    with pytest.raises(ValueError, match="names no image"):
        pc.Image("@string/greeting")
    with pytest.raises(ValueError, match="between 0 and 1"):
        pc.Label({"cat": 2})
    assert pc.Image("@drawable/logo").default == "@drawable/logo"


DOGS = Path(__file__).resolve().parents[1] / "examples/dogs"


def test_the_dogs_example_shows_the_photos_it_downloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    def server(request: httpx.Request) -> httpx.Response:
        if request.url.host == "dog.ceo":
            assert request.url.path == "/api/breed/shiba/images/random/2"
            urls = ["https://images.dog.ceo/a.png", "https://images.dog.ceo/b.png"]
            return httpx.Response(200, json={"message": urls})
        return httpx.Response(200, content=PIXEL)

    real = httpx.Client
    transport = httpx.MockTransport(server)
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=transport, **kw))
    with AppDriver(DOGS) as app:
        app.act("onValueChangeFinished", app.find(type="Slider"), value=2.0)
        app.click(text="Fetch photos")
        app.settle()
        images = [n["props"]["resource"] for n in app.nodes() if n["type"] == "Image"]
        assert len(images) == 3 and all(i.startswith("@file/") for i in images)
