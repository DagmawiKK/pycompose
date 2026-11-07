"""The IR schema writes each definition once, references following the fold."""

from pycompose_codegen.emit.shared_definitions import share_definitions


def _node(children: str, component: str) -> dict:
    return {
        "properties": {"children": {"items": {"$ref": f"#/definitions/{children}"}}},
        "allOf": [{"anyOf": [{"$ref": f"#/definitions/{component}"}]}],
    }


def test_an_unchanged_version_folds_into_the_current_definitions() -> None:
    button = {"properties": {"type": {"const": "Button"}}}
    schema = {
        "definitions": {
            "Button": button,
            "Node": _node("Node", "Button"),
            "V_1_2_0_Button": dict(button),
            "V_1_2_0_Node": _node("V_1_2_0_Node", "V_1_2_0_Button"),
        },
        "allOf": [{"then": {"$ref": "#/definitions/V_1_2_0_Node"}}],
    }
    shared = share_definitions(schema)
    assert set(shared["definitions"]) == {"Button", "Node"}
    assert shared["allOf"] == [{"then": {"$ref": "#/definitions/Node"}}]


def test_versions_that_differ_keep_their_own_and_share_the_rest() -> None:
    old = {"properties": {"type": {"const": "Sheet"}, "open": {}}}
    new = {"properties": {"type": {"const": "Sheet"}, "value": {}}}
    schema = {
        "definitions": {
            "Sheet": new,
            "V_1_1_0_Sheet": old,
            "V_1_2_0_Sheet": dict(old),
            "V_1_3_0_Sheet": dict(new),
        }
    }
    assert set(share_definitions(schema)["definitions"]) == {"Sheet", "V_1_1_0_Sheet"}
