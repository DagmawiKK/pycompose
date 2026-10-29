"""The screen below the top, drawn on demand for the host's predictive back.

When a back gesture starts, the host asks for the ``below`` surface and shows
it behind the screen the user is dragging away. It is a picture of where back
leads, drawn from that screen's current state; nothing on it can be tapped,
since committing the gesture makes it the main screen again.
"""

from __future__ import annotations

import itertools

from pycompose.bridge.protocol import AppSession
from pycompose.core.reuse import Reuse
from pycompose.ir import emit_ir, validate_ir
from pycompose.ir.host import Host, hosted
from pycompose.ir.patch import full_bytes

__all__ = ["BELOW_SURFACE", "preview_envelope"]

BELOW_SURFACE = "below"
"""The surface showing the screen a back gesture leads to."""

_SERIALS = itertools.count(1)


def preview_envelope(
    session: AppSession, host: Host, schema_version: str, *, debug: bool
) -> str:
    """Return the screen below the top as a whole envelope, or empty when none.

    Args:
        session: The app's back stack.
        host: What the host renders, so lacking components get their fallbacks.
        schema_version: The wire contract the host speaks.
        debug: Validate the picture as a published snapshot is validated.

    Returns:
        The envelope as canonical JSON, or empty for a stack of one screen.
    """
    state = session.snapshot_below()
    if state is None:
        return ""
    with hosted(host):
        emitted = emit_ir(state, schema_version, Reuse())
        if debug:
            validate_ir(emitted)
    serial = next(_SERIALS)
    return full_bytes(emitted, serial=serial, surface=BELOW_SURFACE).decode("utf-8")
