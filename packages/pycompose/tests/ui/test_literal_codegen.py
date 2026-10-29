"""Token annotations generated from the manifest's committed enums (plan 18.5).

The property is IDE-level: an enum-constrained prop autocompletes its token
scale because the annotation is generated from the same the catalog lock
enum the validator enforces -- one source, not a stub beside it.
"""

from __future__ import annotations

from typing import get_args

from pycompose import values
from pycompose.material3 import generated_components
from pycompose.material3.generated_components import Text


def test_an_enum_prop_with_a_value_type_keeps_its_literal() -> None:
    # Text.style is both an enum and a value-typed prop; the token scale wins
    # the annotation, because the wire value is the bare token string.
    style = eval(Text.__init__.__annotations__["style"], vars(generated_components))

    vocabulary = get_args(get_args(style)[0])
    assert "bodyLarge" in vocabulary
    assert "titleSmall" in vocabulary


def test_material_icon_names_are_the_shipped_vocabulary() -> None:
    name = eval(values.materialIcon.__annotations__["name"], vars(values))

    vocabulary = get_args(name)
    assert "Filled.Add" in vocabulary
    assert "AutoMirrored.Filled.Send" in vocabulary
