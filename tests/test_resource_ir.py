"""Versioned resource declarations reach the native host as names, never R ids."""

import pytest

from pycompose.errors import IrValidationError
from pycompose.ir import emit_ir, to_json, to_json_bytes, validate_ir
from pycompose.m3 import Column, Image, Text
from pycompose.state import State
from pycompose.testing.helpers import read_golden


def test_resource_props_and_images_require_the_new_schema() -> None:
    state = State(
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
    ],
)
def test_bad_resource_names_fail_closed(reference: str) -> None:
    with pytest.raises(IrValidationError):
        Image(id="image", resource=reference)


def test_resource_screen_matches_shared_native_golden() -> None:
    state = State(
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
                    resource="@drawable/ic_pycompose",
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
