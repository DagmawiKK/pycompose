"""Browse photos of a dog breed from the free Dog CEO API.

The host loads nothing from the network: the app downloads each photo and
shows it as a file, through an image output.
"""

import httpx

import pycompose.app.blocks as pc

API = "https://dog.ceo/api/breed/{breed}/images/random/{count}"
BREEDS = ["shiba", "husky", "corgi", "beagle", "pug", "samoyed"]


def fetch(breed: str, count: float) -> tuple[bytes, list[bytes], list[str]]:
    """Download a few photos of a breed: the first large, all in the grid."""
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        found = client.get(API.format(breed=breed, count=int(count))).json()
        urls = found["message"]
        photos = [client.get(url).content for url in urls]
    return photos[0], photos, urls


with pc.Blocks() as app:
    breed = pc.Dropdown(BREEDS, "shiba", label="Breed")
    count = pc.Slider(1, 8, 4, step=1, label="Photos")
    go = pc.Button("Fetch photos")
    with pc.Tabs():
        with pc.Tab("Photos"):
            first = pc.Image(label="Pick of the bunch")
            grid = pc.Gallery(label="All of them")
        with pc.Tab("Sources"):
            sources = pc.JSON(label="Photo addresses")
    go.click(fetch, inputs=[breed, count], outputs=[first, grid, sources])
