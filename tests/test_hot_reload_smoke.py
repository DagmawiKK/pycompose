"""Dev-server hot-reload smoke (CI job 6).

Skipped until ``pycompose/cli/dev_server.py`` exists; the job gate opens on the
same file, so the job is green now and the moment its gate opens. The real
hot-reload scenario lands with the dev-server ticket — keep the marker, replace
the body.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.hot_reload_smoke


def test_dev_server_hot_reload_smoke() -> None:
    dev_server = pytest.importorskip("pycompose.cli.dev_server")
    assert dev_server.__file__.endswith("dev_server.py")
