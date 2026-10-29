"""Edit a photo from the phone's gallery: pick it, choose a look, turn it.

The system photo picker needs no permission; the app gets a copy of the one
photo picked, and the edit runs on the I/O pool, off the screen's thread.
"""

from PIL import Image as Picture
from PIL import ImageFilter, ImageOps

import pycompose.blocks as pc

LOOKS = ["Original", "Black and white", "Soft focus", "Outline"]


def edit(
    photo: str | None, look: str, turn: float
) -> tuple[Picture.Image | None, dict]:
    """Apply the look and the turn to a copy of the photo, at screen size."""
    if photo is None:
        return None, {}  # nothing picked yet: nothing to show
    with Picture.open(photo) as opened:
        picture = ImageOps.exif_transpose(opened).convert("RGB")
    picture.thumbnail((1600, 1600))
    if look == "Black and white":
        picture = ImageOps.grayscale(picture)
    elif look == "Soft focus":
        picture = picture.filter(ImageFilter.GaussianBlur(4))
    elif look == "Outline":
        picture = picture.filter(ImageFilter.CONTOUR)
    picture = picture.rotate(-turn, expand=True)
    return picture, {"width": picture.width, "height": picture.height, "look": look}


with pc.Blocks() as app:
    photo = pc.Image(label="Your photo", interactive=True)
    look = pc.Radio(LOOKS, "Original", label="Look")
    turn = pc.Slider(0, 270, 0, step=90, label="Turn")
    with pc.Tabs():
        with pc.Tab("Edited"):
            edited = pc.Image(label="Edited")
        with pc.Tab("Details"):
            details = pc.JSON(label="Size")
    for control in (photo, look, turn):
        control.change(edit, inputs=[photo, look, turn], outputs=[edited, details])
