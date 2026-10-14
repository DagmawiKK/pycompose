"""Read the classpath dump, and say what PyCompose could do with each composable.

    ./gradlew dumpComposeApi        # writes android/build/compose-api/*.json
    python tools/schema/classpath_dump.py

This replaces the older route through AndroidX's published ``current.txt``, which
had nowhere to read a version that matched the pinned BOM. See
``android/dump-compose-api.gradle.kts`` for why reading bytecode is the only
source that cannot drift.

The dump is already a better answer than the text file was, because the
distinction that matters is *in* it rather than inferred from it:

    Button(onClick: Function0<Unit>, ..., content: Function1<RowScope>)
    Checkbox(checked: Boolean, onCheckedChange: Function1<Boolean>, ...)

A content slot and a real callback are both Kotlin function types, and
``Function0`` is the single most common parameter in Material 3 -- 469 of them
against 181 genuine callbacks. Reading every zero-argument function as a
callback would model "click this to close the dialog" for what is really "render
this here", and the error would not surface until someone tapped the wrong
thing.

What this module still has to decide, and what it deliberately does not:

* Whether a composable is stable enough to expose at all. The dump records the
  name and signature; stability is a design judgement.
* Defaults, requiredness, children. The dump cannot tell you what ``enabled``
  defaults to, and inventing one is a decision a person makes.
* Overloads. ``Text`` lists its ``AnnotatedString`` variants first and its
  ``String`` one last; neither "first" nor "widest" picks correctly, so the
  most-crossing overload wins.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

__all__ = [
    "DUMP_DIR",
    "Kind",
    "Parameter",
    "Composable",
    "load",
    "composables",
    "summarise",
]

DUMP_DIR = Path("android/build/compose-api")
"""Where ``./gradlew dumpComposeApi`` writes. Gitignored: it is build output
read from the resolved classpath, never a checked-in source of truth."""


class Kind(Enum):
    """What a parameter is, from the wire's point of view.

    The point of the enum is that the three cases look identical in a signature
    and must not be treated alike.
    """

    VALUE = "value"
    """A plain value: Compose takes it as a Kotlin type, so the wire carries
    something of the same shape."""

    CALLBACK = "callback"
    """Something the app can be told about: ``onClick``, ``onCheckedChange``.

    A ``Function1`` whose single argument is a value. That argument is the
    payload the action reports, and dropping it compiles and then reports
    nothing."""

    SLOT = "slot"
    """Content the component renders: ``content``, ``label``, ``placeholder``.

    A ``Function0`` or a scoped ``Function1``. Never an actionId, whatever its
    arity -- ``ModalBottomSheet``'s ``onDismissRequest`` and its ``content``
    are both function types, and they mean opposites.
    """

    UNKNOWN = "unknown"
    """A type this reader does not yet model. Refused rather than guessed."""


_SCOPED = {
    "ColumnScope",
    "RowScope",
    "BoxScope",
    "LazyItemScope",
    "LazyListScope",
    "LazyGridItemScope",
    "FlowRowScope",
    "FlowColumnScope",
    "CardScope",
    "ChipScope",
    "ButtonScope",
    "MenuScope",
    "DialogScope",
    "DrawerScope",
    "TooltipScope",
}
"""Compose scopes that turn a Function1 into a content slot rather than a
callback.

This is the trap the whole approach exists to avoid. ``RowScope.() -> Unit`` and
``(Boolean) -> Unit`` have the same arity; only the parameter's type separates
"render this between these weights" from "the user tapped this".
"""


@dataclass(frozen=True, slots=True)
class Parameter:
    """One composable parameter.

    Attributes:
        name: The Kotlin parameter name.
        type: The rendered Kotlin type.
        kind: What it means on the wire.
        optional: Whether the dump says so.
    """

    name: str
    type: str
    kind: Kind
    optional: bool = False

    @property
    def payload(self) -> str | None:
        """Return the callback's payload type, if it carries one.

        A ``Function1<Boolean>`` reports the boolean; a ``Function1<RowScope>``
        is a slot with a scope and carries nothing.

        Returns:
            The argument's type name, or None.
        """
        if self.kind is not Kind.CALLBACK:
            return None
        inner = self.type.partition("<")[2].rpartition(">")[0].split(",")[0]
        return inner or None


@dataclass(frozen=True, slots=True)
class Composable:
    """One @Composable function.

    Attributes:
        name: The function's simple name.
        package: The package its file facade lives in.
        parameters: Every parameter, in declaration order.
        overloads: How many overloads share this name.
    """

    name: str
    package: str
    parameters: tuple[Parameter, ...]
    overloads: int = 1

    @property
    def slots(self) -> tuple[Parameter, ...]:
        """Return the content slots.

        Returns:
            Every parameter that renders content.
        """
        return tuple(p for p in self.parameters if p.kind is Kind.SLOT)

    @property
    def callbacks(self) -> tuple[Parameter, ...]:
        """Return the callbacks an app can be told about.

        Returns:
            Every parameter that reports something.
        """
        return tuple(p for p in self.parameters if p.kind is Kind.CALLBACK)


_SIGNATURE = re.compile(r"^(\w+)\((.*)\)$", re.DOTALL)
# Not anchored: findall over one parameter only ever matched the first, which
# is why Checkbox appeared to have no callback at all.
_PARAM = re.compile(r"(\w+): (.+?)(?=, \w+: |$)", re.DOTALL)
_FUNCTION = re.compile(r"^Function(\d+)(?:<(.+)>)?$")
_SIMPLE = re.compile(r"^[\w.]+$")
_OPTIONAL = re.compile(r"= null")


def _classify(type_name: str) -> Kind:
    """Decide what a parameter's Kotlin type means on the wire.

    Args:
        type_name: The rendered Kotlin type.

    Returns:
        The parameter's kind.
    """
    function = _FUNCTION.match(type_name)
    if function is None:
        if _SIMPLE.match(type_name):
            return Kind.VALUE
        return Kind.UNKNOWN
    arity, inner = int(function.group(1)), function.group(2) or ""
    if arity == 0:
        # Zero arguments: there is nothing for the app to report, so whatever
        # the name suggests this renders content.
        return Kind.SLOT
    head = inner.split(",")[0].strip()
    if head in _SCOPED:
        # A scope is something Compose provides, not something the app sends.
        return Kind.SLOT
    if arity == 1:
        return Kind.CALLBACK
    return Kind.UNKNOWN


def _parse(signature: str) -> tuple[str, tuple[Parameter, ...]] | None:
    """Read one rendered signature.

    Args:
        signature: ``name(a: T, b: U)`` as the dump writes it.

    Returns:
        The name and its parameters, or None when the shape is unrecognised.
    """
    match = _SIGNATURE.match(signature.strip())
    if match is None:
        return None
    name, body = match.group(1), match.group(2)
    parameters: list[Parameter] = []
    if body.strip():
        for raw in _PARAM.findall(body):
            prop, type_name = raw[0], raw[1].strip()
            if not type_name:
                continue
            parameters.append(
                Parameter(
                    name=prop,
                    type=type_name,
                    kind=_classify(type_name),
                    optional=_OPTIONAL.search(type_name) is not None,
                )
            )
    if not parameters and body.strip():
        return None
    return name, tuple(parameters)


def load(directory: Path = DUMP_DIR) -> dict[str, dict[str, list[str]]]:
    """Read every artifact the dump wrote.

    Args:
        directory: Where the JSON files live.

    Returns:
        Raw ``{class: [signature, ...]}`` per artifact, keyed by filename.

    Raises:
        FileNotFoundError: If the directory does not exist. Almost always
            because ``./gradlew dumpComposeApi`` has not been run, and saying
            so beats reporting an empty catalog.
    """
    if not directory.is_dir():
        raise FileNotFoundError(
            f"{directory} does not exist; run ./gradlew dumpComposeApi first"
        )
    artifacts: dict[str, dict[str, list[str]]] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            artifacts[path.name] = payload
    return artifacts


def _most_crossing(
    groups: dict[str, list[tuple[str, tuple[Parameter, ...]]]],
) -> Iterator[Composable]:
    """Yield one composable per name, choosing the widest overload.

    ``Text`` lists its ``AnnotatedString`` overloads first and its ``String`` one
    last, so neither "first" nor "widest" picks the plain one a caller wants.
    The most-crossing signature is the one sharing the most parameter names with
    the others, which is the stable shape and the one the Kotlin overload rules
    are built around.

    Args:
        groups: Parsed signatures grouped by composable name.

    Yields:
        Composable: The chosen overload, one per name.
    """
    for name, candidates in sorted(groups.items()):
        counts = {id(candidate): 0 for candidate in candidates}
        for a in candidates:
            names_a = {p.name for p in a[1]}
            for b in candidates:
                if a is b:
                    continue
                counts[id(a)] += len(names_a & {p.name for p in b[1]})
        best = max(candidates, key=lambda c: _rank(c, counts[id(c)]))
        package = best[0].rsplit(".", 1)[0] if "." in best[0] else ""
        yield Composable(
            name=name,
            package=package,
            parameters=best[1],
            overloads=len(candidates),
        )


def _plainness(signature: tuple[str, tuple[Parameter, ...]]) -> str:
    """Return a sort key that prefers plain types over wrapper types.

    Args:
        signature: The parsed signature.

    Returns:
        A string, lower sorting first.
    """
    types = sorted({p.type for p in signature[1]})
    return "".join(sorted({t[0] for t in types}))


def _priority(signature: tuple[str, tuple[Parameter, ...]]) -> int:
    """Prefer the plainer of two equally plausible overloads.

    ``Text`` is overloaded on ``String`` and on ``AnnotatedString`` with
    otherwise identical parameters, so most-crossing cannot separate them -- it
    ties, and the list order then decides, which is not a decision anyone
    should inherit. A plain String is what an app writes; AnnotatedString is the
    richer form Compose offers for spans and styles.
    """
    first = signature[1][0].type if signature[1] else ""
    # Higher wins, because the rank is compared with max(). Getting this
    # backwards is invisible in the output and simply selects the wrong
    # overload.
    return 1 if first == "String" else 0


def _rank(signature: tuple[str, tuple[Parameter, ...]], crossings: int) -> tuple:
    """Order overloads: most crossing first, then plainest, then deterministic.

    Args:
        signature: The parsed signature.
        crossings: How many parameter names it shares with its siblings.

    Returns:
        A sort key; larger is better.
    """
    unmodelled = sum(1 for p in signature[1] if p.kind is Kind.UNKNOWN)
    return (
        # What an app can pass decides, before anything else. `Text` is
        # overloaded on String and AnnotatedString; both are real, but a String
        # is what an app writes, and a schema offering only AnnotatedString makes
        # every caller construct one by hand.
        _priority(signature),
        crossings,
        -unmodelled,
        # Lexical on the rendered signature so the choice never depends on
        # dictionary or file order.
        "".join(p.type for p in signature[1]),
    )


def composables(directory: Path = DUMP_DIR) -> dict[str, Composable]:
    """Return every composable in the dump, one per name.

    Args:
        directory: Where the JSON files live.

    Returns:
        Composables keyed by name.
    """
    groups: dict[str, list[tuple[str, tuple[Parameter, ...]]]] = {}
    for payload in load(directory).values():
        for class_name, signatures in payload.items():
            for signature in signatures:
                parsed = _parse(signature)
                if parsed is None:
                    continue
                groups.setdefault(parsed[0], []).append((class_name, parsed[1]))
    return {c.name: c for c in _most_crossing(groups)}


def summarise(directory: Path = DUMP_DIR) -> str:
    """Describe what the dump contains, for a human.

    Args:
        directory: Where the JSON files live.

    Returns:
        A short report.
    """
    found = composables(directory)
    slots = sum(len(c.slots) for c in found.values())
    callbacks = sum(len(c.callbacks) for c in found.values())
    unknown = sum(
        1 for c in found.values() for p in c.parameters if p.kind is Kind.UNKNOWN
    )
    overloads = sum(1 for c in found.values() if c.overloads > 1)
    return (
        f"{len(found)} composables across {len(load(directory))} artifacts\n"
        f"  {slots} content slots, {callbacks} callbacks, {unknown} unmodelled types\n"
        f"  {overloads} names with overloads, resolved to the most-crossing"
    )


def main(argv: Iterable[str] | None = None) -> int:
    """Print a summary of the classpath dump.

    Args:
        argv: Unused; present so the signature matches the other tools.

    Returns:
        Process exit code.
    """
    del argv
    try:
        print(summarise())
    except FileNotFoundError as exc:
        print(f"classpath_dump.py: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
