"""core.props: snake_case <-> camelCase wire-name helpers."""

from __future__ import annotations

from pycompose.core.props import (
    is_camel_case,
    props_from_kwargs,
    to_camel_case,
    to_snake_case,
)


def test_to_camel_case() -> None:
    assert to_camel_case("on_click") == "onClick"
    assert to_camel_case("on_value_change") == "onValueChange"
    assert to_camel_case("text") == "text"
    assert to_camel_case("") == ""


def test_to_snake_case() -> None:
    assert to_snake_case("onValueChange") == "on_value_change"
    assert to_snake_case("bodyLarge") == "body_large"
    assert to_snake_case("text") == "text"


def test_is_camel_case() -> None:
    assert is_camel_case("onValueChange")
    assert not is_camel_case("on_click")
    assert not is_camel_case("OnClick")
    assert not is_camel_case("")


def test_props_from_kwargs_maps_snake_case_to_camel_case() -> None:
    assert props_from_kwargs(on_click="increment", label="Name") == {
        "onClick": "increment",
        "label": "Name",
    }
