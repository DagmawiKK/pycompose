"""Versioned resource declarations reach the native host as names, never R ids."""

import pytest
from goldens import read_golden

from pycompose.errors import IrValidationError
from pycompose.host.wire import emit_ir, to_json, to_json_bytes, validate_ir
from pycompose.model.snapshot import Snapshot
from pycompose.ui import Column, Image, Text


def test_resource_props_and_images_require_the_new_schema() -> None:
    state = Snapshot(
        root=Column(
            id="screen",
            children=[
                Text(
                    id="title",
                    text="fallback",
                    resource="@string/greeting",
                    locale="fr",
                ),
                Image(id="logo", resource="@drawable/logo", content_description="Logo"),
                Image(id="asset", resource="@asset/images/avatar.png"),
            ],
        )
    )
    snapshot = emit_ir(state, "1.1.0")
    assert validate_ir(snapshot).snapshot is snapshot
    assert '"resource":"@string/greeting"' in to_json(snapshot)
    with pytest.raises(IrValidationError, match="schema"):
        validate_ir(emit_ir(state, "1.0.0"))


@pytest.mark.parametrize(
    "reference",
    [
        "@asset/../private",
        "@string/bad/name",
        "@drawable/Logo",
        "https://example.com/a.png",
        "@file/cat.png",
        "@file/" + "a" * 64 + ".exe",
        "@file/../" + "a" * 64 + ".png",
    ],
)
def test_bad_resource_names_fail_closed(reference: str) -> None:
    with pytest.raises(IrValidationError):
        Image(id="image", resource=reference)


def test_a_media_file_is_named_by_its_digest() -> None:
    Image(id="image", resource="@file/" + "0f" * 32 + ".png")


def test_resource_screen_matches_shared_native_golden() -> None:
    state = Snapshot(
        root=Column(
            id="screen",
            children=[
                Text(
                    id="title",
                    text="Fallback",
                    resource="@string/pycompose_greeting",
                    locale="fr",
                ),
                Image(
                    id="image",
                    resource="@drawable/app_icon",
                    content_description="PyCompose logo",
                ),
                Text(
                    id="asset",
                    text="Fallback asset",
                    resource="@asset/demo/message.txt",
                ),
            ],
        )
    )
    assert to_json_bytes(emit_ir(state, "1.1.0")) == read_golden("resource_screen.json")
