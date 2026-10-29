"""Emit native calls from unapproved overload plans, not component registrations.

The JSON prop reader and typed native slots are a compiler-test seam. This does
not define a new IR encoding or make a component available to Python. Catalog
approval, slot transport/context, and guarded renderer integration remain separate.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pycompose.core.values import FLOAT_MAX, FLOAT_MIN
from pycompose_codegen.emit.defaults import render_default
from pycompose_codegen.emit.values import resolver_call

_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
_READERS = {
    "kotlin/String": "content",
    "kotlin/Boolean": "boolean",
    "kotlin/Int": "int",
    "kotlin/Long": "long",
    "kotlin/Float": "float",
    "kotlin/Double": "double",
}


def _name(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError("invalid native identifier")
    return f"`{value}`"


def _qualified(value: str) -> str:
    return ".".join(_name(part) for part in value.replace("/", ".").split("."))


def call_name(plan: dict[str, Any]) -> str:
    """Return a stable overload-specific symbol, including artifact and JVM name.

    Args:
        plan: An exact overload plan from the proposal tool.

    Returns:
        A deterministic Kotlin identifier independent of inventory iteration order.
    """
    digest = hashlib.sha256(
        json.dumps(plan["source"], sort_keys=True).encode()
    ).hexdigest()[:16]
    return "binding_" + digest


def _type(document: dict[str, Any]) -> str:
    if document.get("arguments"):
        raise ValueError("generic native type needs a binding policy")
    return _qualified(document["classifier"]) + ("?" if document["nullable"] else "")


def _slot_type(spec: dict[str, Any]) -> str:
    """The slot's exact native function type: receiver, arguments, composability.

    A slot whose receiver the renderer does not provide, a slot whose content
    receives an argument it consumes, and a lazy list's builder all keep the
    pinned type, so the facade proves the call the adapter makes.
    """
    document = spec["type"]
    *parameters, result = (argument["type"] for argument in document["arguments"])
    receiver = ""
    if "kotlin/ExtensionFunctionType" in document["annotations"]:
        receiver = _type(parameters.pop(0)) + "."
    composable = (
        "@Composable "
        if "androidx/compose/runtime/Composable" in document["annotations"]
        else ""
    )
    values = ", ".join(_type(parameter) for parameter in parameters)
    return f"({composable}{receiver}({values}) -> {_type(result)})" + (
        "?" if document["nullable"] else ""
    )


def _event_type(spec: dict[str, Any]) -> str:
    arguments = spec["type"]["arguments"][:-1]
    return (
        "(("
        + ", ".join(_type(a["type"]) for a in arguments)
        + ") -> Unit)"
        + ("?" if spec["type"]["nullable"] else "")
    )


def _event(spec: dict[str, Any], raw: str) -> str:
    names = [field["name"] for field in spec["payload"]]
    if not names:
        payload = "JsonNull"
    elif len(names) == 1:
        payload = f"JsonPrimitive({names[0]})"
    else:
        payload = (
            "JsonObject(mapOf("
            + ", ".join(f'"{n}" to JsonPrimitive({n})' for n in names)
            + "))"
        )
    args = ", ".join(names) + " -> " if names else ""
    nonnull = _event_type(spec).removesuffix("?")
    return (
        f"run {{ val action = {raw}.jsonPrimitive"
        ".also { require(it.isString) }.content; "
        f"val callback: {nonnull} = {{ {args}dispatch(action, {payload}) }}; "
        "callback }"
    )


def _decode(spec: dict[str, Any], raw: str) -> str:
    if spec["policy"] == "event":
        return _event(spec, raw)
    if spec["policy"] == "value":
        return resolver_call(spec["family"], raw) + ".getOrThrow()"
    classifier = spec["type"]["classifier"]
    string = "true" if classifier == "kotlin/String" else "false"
    guard = f"{raw}.jsonPrimitive.also {{ require(it.isString == {string}) }}"
    if classifier in {"kotlin/Float", "kotlin/Double"}:
        return _number(classifier, guard)
    reader = _READERS.get(classifier)
    if reader is None:
        raise ValueError("scalar has no JSON reader")
    return f"{guard}.{reader}"


def _number(classifier: str, guard: str) -> str:
    """Read a JSON number, refusing floats no native ``Float`` represents.

    A number outside ``Float``'s range would reach Compose as Infinity or as
    zero rather than the number the snapshot states, so it is rejected instead
    of narrowed silently. The bounds come from the same constants the schema
    validator uses, so Python and Kotlin cannot drift apart.
    """
    if classifier == "kotlin/Double":
        return f"{guard}.double.also {{ require(it.isFinite()) }}"
    largest = repr(FLOAT_MAX)
    smallest = repr(FLOAT_MIN)
    bounded = (
        f"it.isFinite() && it >= -{largest} && it <= {largest}"
        f" && (it == 0.0 || it >= {smallest} || it <= -{smallest})"
    )
    return f"{guard}.double.also {{ require({bounded}) }}.toFloat()"


class _Call:
    """Collects the signature, forwarded arguments and prop readers for one plan."""

    def __init__(
        self, plan: dict[str, Any], imports: set[str], parameters: list[str]
    ) -> None:
        """Bind the plan, its import collector and the signature being built."""
        self.plan = plan
        self.imports = imports
        self.parameters = parameters
        self.arguments: list[str] = []
        self.locals: list[str] = []
        self.accepted: list[str] = []

    def add(self, name: str, spec: dict[str, Any]) -> None:
        """Route one parameter to a forwarded argument or a typed reader."""
        policy = spec["policy"]
        if policy == "omit":
            # No policy reaches this prop, so Compose's own default stays in
            # charge; the guard refuses the key rather than ignoring a value.
            return
        if policy == "modifier":
            value = "modifier"
        elif policy == "slot":
            value = _slot_parameter(name, spec, self.parameters)
        elif policy in {"holder", "provider", "resource", "transient", "hostValue"}:
            # The host fills these -- a holder it drives, a late read, a loaded
            # resource, a value it builds -- so the facade takes them typed.
            value = _name("host_" + name)
            self.parameters.append(f"    {value}: {_host_type(spec)},")
        elif policy in {"scalar", "value", "event"}:
            self.accepted.append(json.dumps(name))
            self.locals.append(_local(name, spec, self.imports))
            value = _name("arg_" + name)
        else:
            raise ValueError(f"blocked parameter policy: {policy}")
        self.arguments.append(f"        {_name(name)} = {value},")


def _host_type(spec: dict[str, Any]) -> str:
    if spec["policy"] != "provider":
        return _type(spec["type"])
    returns = spec["type"]["arguments"][-1]["type"]
    return f"(() -> {_type(returns)})"


def _slot_parameter(name: str, spec: dict[str, Any], parameters: list[str]) -> str:
    """Add a typed slot parameter; only a null default is renderable."""
    value = _name("slot_" + name)
    if spec["required"]:
        parameters.append(f"    {value}: {_slot_type(spec)},")
        return value
    # Only an absent or null default is renderable, matching the planner's rule.
    # Anything else needs a native protocol and would change what renders.
    fallback = spec.get("default", {})
    if (
        not spec["type"]["nullable"]
        or fallback.get("kind") != "literal"
        or fallback.get("value") is not None
    ):
        raise ValueError("optional slot needs an explicit null policy")
    parameters.append(f"    {value}: {_slot_type(spec)} = null,")
    return value


def _local(name: str, spec: dict[str, Any], imports: set[str]) -> str:
    variable = _name("arg_" + name)
    raw = _name("raw_" + name)
    native_type = (
        _event_type(spec) if spec["policy"] == "event" else _type(spec["type"])
    )
    default = (
        render_default(spec["default"], imports)
        if "default" in spec
        else f'error("Missing {name}")'
    )
    null = "null" if spec["type"]["nullable"] else f'error("Non-null {name}")'
    return (
        f"    val {raw} = props[{json.dumps(name)}]\n"
        f"    val {variable}: {native_type} = when ({raw}) {{\n"
        f"        null -> {default}\n"
        f"        JsonNull -> {null}\n"
        f"        else -> {_decode(spec, raw)}\n"
        "    }"
    )


def render_call(plan: dict[str, Any], *, package: str) -> str:
    """Emit a typed composable call for one overload; do not register or enable it.

    Args:
        plan: Policy-derived overload plan, including explicit omissions.
        package: Native package for this generated compiler-test facade.

    Returns:
        Kotlin source accepting JSON scalar/value/action props and typed slots.

    Raises:
        ValueError: A required capability is blocked or the plan is not renderable.
    """
    if plan["status"] != "call-plan" or any(g["required"] for g in plan["gaps"]):
        raise ValueError("blocked native call plan")
    imports = {
        "import androidx.compose.runtime.Composable",
        "import androidx.compose.ui.Modifier",
        "import kotlinx.serialization.json.*",
    }
    imports.add(f"import {_qualified(plan['call'])} as nativeCall")
    parameters = [
        "    props: JsonObject,",
        "    modifier: Modifier = Modifier,",
        "    dispatch: (String, JsonElement) -> Unit = { _, _ -> },",
    ]
    call = _Call(plan, imports, parameters)
    for name, spec in plan["parameters"].items():
        call.add(name, spec)
    arguments = call.arguments
    locals_ = call.locals
    accepted = call.accepted
    receiver = _type(plan["receiver"]) + "." if plan["receiver"] else ""
    opt_in = ""
    if plan["optIn"]:
        opt_in = (
            "@OptIn("
            + ", ".join(_qualified(a) + "::class" for a in plan["optIn"])
            + ")\n"
        )
    return (
        "// Generated native-call proof. Not an approved component adapter.\n"
        f"package {_qualified(package)}\n\n"
        + "\n".join(sorted(imports))
        + "\n\n"
        + opt_in
        + "@Composable\n"
        + f"fun {receiver}{call_name(plan)}(\n"
        + "\n".join(parameters)
        + "\n) {\n"
        + "    require(props.keys.all { it in "
        + f"setOf<String>({', '.join(accepted)}) }})"
        + ' { "Unsupported prop" }\n'
        + "\n".join(locals_)
        + "\n    nativeCall(\n"
        + "\n".join(arguments)
        + "\n    )\n}\n"
    )
