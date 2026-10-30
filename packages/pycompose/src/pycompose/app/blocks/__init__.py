"""pycompose.app.blocks — an app from components, events and plain functions.

Declare the screen in a ``with`` block; connect components with events that
name a function, the components it reads and the ones it writes::

    import pycompose.app.blocks as pc

    def greet(name):
        return f"Hello, {name}"

    with pc.Blocks() as app:
        name = pc.Textbox(label="Name")
        greeting = pc.Textbox(label="Greeting", interactive=False)
        pc.Button("Greet").click(greet, inputs=name, outputs=greeting)

Every component is drawn from native Material 3 components. A function runs
off the loop thread (an ``async def`` one on it), so a slow network call never
freezes the screen; its outputs show progress until it returns, and an error
becomes a toast. A function that yields streams: each value it yields is shown
as it arrives, which is how a chat reply appears word by word.
"""

from pycompose.app.blocks.app import Blocks, Interface
from pycompose.app.blocks.chat import Chatbot, ChatInterface
from pycompose.app.blocks.components import Button, Component
from pycompose.app.blocks.containers import Accordion, Column, Row, Tab, Tabs
from pycompose.app.blocks.display import JSON, Gallery, Image, Label
from pycompose.app.blocks.layout import Event
from pycompose.app.blocks.selection import Checkbox, Dropdown, Radio, Slider
from pycompose.app.blocks.text import Markdown, Number, Textbox
from pycompose.app.blocks.upload import File, UploadButton

__all__ = [
    "Accordion",
    "Blocks",
    "Button",
    "ChatInterface",
    "Chatbot",
    "Checkbox",
    "Column",
    "Component",
    "Dropdown",
    "Event",
    "File",
    "Gallery",
    "Image",
    "Interface",
    "JSON",
    "Label",
    "Markdown",
    "Number",
    "Radio",
    "Row",
    "Slider",
    "Tab",
    "Tabs",
    "Textbox",
    "UploadButton",
]
