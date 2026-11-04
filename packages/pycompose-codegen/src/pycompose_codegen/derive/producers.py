"""Producer interfaces: a value a component asks for while it draws.

``BasicText(color: ColorProducer?)`` takes an object whose one method the text
calls each time it draws, so a colour can change frame by frame without the
text recomposing. An interface whose only member is an abstract function of no
arguments that returns a value is such a producer, exactly as a ``() -> Float``
lambda is (one returning ``Unit`` is a command, not a value): the
parameter becomes a prop of the type it produces, read inside the producer.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_dump import Inventory


def producer_interfaces(found: Inventory) -> dict[str, dict[str, Any]]:
    """Every public interface whose one member produces a value, by classifier.

    Args:
        found: The pinned inventory.

    Returns:
        Per slash classifier: the interface's dotted name, its member's name and
        the type it returns.
    """
    interfaces = {
        c.classifier.replace(".", "/")
        for c in found.classes
        if c.class_kind == "INTERFACE"
        and c.visibility == "PUBLIC"
        and set(c.supertypes) <= {"kotlin/Any"}
    }
    members: dict[str, list[Any]] = {}
    for d in found.declarations:
        if (
            d.dispatch_receiver is not None
            and d.dispatch_receiver.classifier in interfaces
        ):
            members.setdefault(d.dispatch_receiver.classifier, []).append(d)
    producers = {}
    for classifier, declared in sorted(members.items()):
        if len(declared) != 1:
            continue
        (member,) = declared
        if (
            member.document.get("declarationKind") == "function"
            and member.document.get("modality") == "ABSTRACT"
            and member.document.get("visibility") == "PUBLIC"
            and not member.parameters
            and not member.document.get("suspend")
            and not member.document.get("typeParameters")
            and not member.composable
            and member.receiver is None
            and member.return_type.classifier != "kotlin/Unit"
            and not member.return_type.nullable
            and not member.return_type.arguments
        ):
            producers[classifier] = {
                "interface": classifier.replace("/", "."),
                "member": member.name,
                "returns": member.return_type,
            }
    return producers
