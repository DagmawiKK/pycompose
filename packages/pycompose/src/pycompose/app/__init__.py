"""pycompose.app — view models, intents, typed effects and the app they form.

An app is a container and a destination. A destination builds its view model
from the container and draws the view model's state with a pure screen
function. Controls send intents, the view model handles them on the session's
loop thread, and its tasks run supervised until it is cleared.
"""

from pycompose.app.app import App, Destination, Home
from pycompose.app.effects import TypedEffect
from pycompose.app.flow import StateFlow
from pycompose.app.generated_effects import (
    Finish,
    Haptic,
    Navigate,
    OpenUrl,
    PickFile,
    Toast,
)
from pycompose.app.intents import Intent
from pycompose.app.navigation import Pop, Push, Replace, Route
from pycompose.app.observe import Failure, Span
from pycompose.app.viewmodel import ViewModel
from pycompose.runtime.scheduler import to_thread

__all__ = [
    "App",
    "Destination",
    "Failure",
    "Finish",
    "Haptic",
    "Home",
    "Intent",
    "Navigate",
    "OpenUrl",
    "PickFile",
    "Pop",
    "Push",
    "Replace",
    "Route",
    "Span",
    "StateFlow",
    "Toast",
    "TypedEffect",
    "ViewModel",
    "to_thread",
]
