"""Your app: components, an event, and a plain function.

Edit this file while ``pycompose run`` is watching: the phone reloads on save.
The README lists every component and shows how to stream, pick photos, and
build screens of your own with view models.
"""

import pycompose.blocks as pc


def greet(name: str) -> str:
    """Answer the button: whatever this returns fills the outputs."""
    return f"Hello, {name.strip() or 'world'}!"


with pc.Blocks() as app:
    name = pc.Textbox(label="Your name")
    greeting = pc.Markdown("Type your name and tap Greet.")
    pc.Button("Greet").click(greet, inputs=name, outputs=greeting)
