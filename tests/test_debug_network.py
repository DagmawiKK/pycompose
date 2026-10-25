"""Debug builds reach the dev server; release builds reach nothing they did not ask for.

Found on an emulator: the dev client could not pull its app ("Cleartext HTTP
traffic to 127.0.0.1 not permitted"), and had no INTERNET permission either.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

HOST = Path(__file__).resolve().parents[1] / "android/host/src"
ANDROID = "{http://schemas.android.com/apk/res/android}"


def test_only_debug_builds_may_open_a_socket() -> None:
    def permissions(manifest: Path) -> set[str]:
        root = ET.parse(manifest).getroot()
        return {e.get(f"{ANDROID}name", "") for e in root.iter("uses-permission")}

    assert "android.permission.INTERNET" in permissions(
        HOST / "debug/AndroidManifest.xml"
    )
    assert "android.permission.INTERNET" not in permissions(
        HOST / "main/AndroidManifest.xml"
    )


def test_cleartext_is_allowed_to_the_reversed_loopback_alone() -> None:
    config = ET.parse(HOST / "debug/res/xml/dev_server_network.xml").getroot()
    assert config.find("base-config") is None
    domains = [d for c in config.iter("domain-config") for d in c.iter("domain")]
    assert sorted(d.text or "" for d in domains) == ["127.0.0.1", "localhost"]
    assert all(d.get("includeSubdomains") == "false" for d in domains)
