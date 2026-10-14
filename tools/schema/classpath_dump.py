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
* Default *values*. The dump records only that a default exists, never what it
  is -- and it must not, because most Compose defaults read ambient state
  (``MaterialTheme``, ``LocalContentColor``) and cannot cross a process
  boundary. Presence is enough: an optional prop is omitted from the generated
  adapter and Compose's own default applies.
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


class Wire(Enum):
    """PyCompose's wire vocabulary, as the schema already spells it.

    Deliberately the vocabulary ``components.json`` uses rather than a new one,
    so a generated prop drops into an existing schema entry instead of needing
    a migration. ``None`` from :func:`wire_type` means *not expressible* -- see
    that function for why refusing is the whole point.
    """

    STRING = "string"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    DIMENSION = "dimension"
    COLOR = "color"
    ENUM = "enum"
    EDGES = "edges"
    BRUSH = "brush"
    ACTION = "actionId"
    MODIFIER = "modifier"
    CONTENT = "content"


SCALARS = {
    "String": Wire.STRING,
    "CharSequence": Wire.STRING,
    "Boolean": Wire.BOOLEAN,
    "Int": Wire.INTEGER,
    "Long": Wire.INTEGER,
    "Short": Wire.INTEGER,
    "Byte": Wire.INTEGER,
    "Float": Wire.NUMBER,
    "Double": Wire.NUMBER,
    "Dp": Wire.DIMENSION,
    "DpOffset": Wire.DIMENSION,
    "TextUnit": Wire.DIMENSION,
    "Color": Wire.COLOR,
    "ColorLong": Wire.COLOR,
    "Modifier": Wire.MODIFIER,
}
"""Direct scalar mappings.

Anything a Compose parameter takes whose wire form is the same string the app
would have written maps straight across.
"""

ENUMS = {
    # Layout
    "Shape",
    "Horizontal",
    "Vertical",
    "Orientation",
    "Arrangement",
    "Alignment",
    "AlignmentDirection",
    "LayoutDirection",
    # Text
    "TextAlign",
    "FontStyle",
    "FontWeight",
    "FontFamily",
    "TextDecoration",
    "TextOverflow",
    "TextDirection",
    "SoftKeyboardType",
    "KeyboardType",
    "ImeAction",
    "Capitalization",
    "KeyboardCapitalization",
    "TextUnitType",
    "Hyphens",
    "LineBreak",
    "ContentScale",
    "Alpha",
    "Role",
    # Interaction
    "InteractionSource",
}
"""Families a schema entry declares its own values for.

The family is *declared* rather than inferred from the type: two families can
share a name in different packages, and the wrong one renders a wrong value
rather than failing.
"""

EDGES = {"PaddingValues", "WindowInsets", "DpInsets", "DpInsetsAndCorners", "Padding"}
"""Edge sets, which schema 1.8.0 declares as the `edges` family."""

SIZED = {
    "Dp",
    "DpOffset",
    "TextUnit",
    "Size",
    "IntSize",
    "IntOffset",
    "IntRect",
    "Rect",
    "DpRect",
    "Offset",
    "FloatSize",
}
"""Types carrying a size, which the `dimension` family covers."""


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
        required: True when Compose declares no default, so the app must supply
            it. Derived rather than judged: a parameter with a default is
            omitted from the generated adapter, and Compose's own default
            applies.
    """

    name: str
    type: str
    kind: Kind
    required: bool = True

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
        markers: The ``@Experimental*`` annotations it carries. Empty means
            stable at the pinned version.
    """

    name: str
    package: str
    parameters: tuple[Parameter, ...]
    overloads: int = 1
    markers: tuple[str, ...] = ()

    @property
    def experimental(self) -> bool:
        """Whether the pinned version still considers this experimental.

        Returns:
            True when at least one @Experimental* marker is present.
        """
        return bool(self.markers)

    @property
    def omitted(self) -> tuple[Parameter, ...]:
        """Return the parameters this surface does not expose.

        Every one is recorded rather than dropped: a component present with
        fewer props than Compose declares fails at build time when someone uses
        an omitted one, and a prop that silently vanished fails to be noticed.
        That is the whole reason :func:`wire_type` refuses rather than
        approximates.
        """
        return tuple(p for p in self.parameters if wire_type(p) is None)

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
UNREADABLE = "?"
"""Prefix the dump puts on a parameter whose Kotlin type it could not read.

Rendering the raw JVM type instead would be worse than useless: ``Dp``,
``TextUnit`` and ``Long`` are all ``long`` in the descriptor, so a dimension
prop would be typed as an integer -- quietly wrong rather than absent.
"""

_ANNOTATIONS = re.compile(r"^(?:@(\w+)\s+)+")
_DEFAULT = re.compile(r"\s=\sdefault$")
# Not anchored: findall over one parameter only ever matched the first, which
# is why Checkbox appeared to have no callback at all.
_PARAM = re.compile(r"(\w+): (.+?)(?=, \w+: |$)", re.DOTALL)
_FUNCTION = re.compile(r"^Function(\d+)(?:<(.+)>)?$")
_SIMPLE = re.compile(r"^[\w.]+$")


def wire_type(parameter: Parameter) -> Wire | None:
    """Map a parameter to PyCompose's wire type, or None when it has none.

    The refusal is the point. Compose parameters carry types that cannot cross a
    process boundary at all -- ``Animatable``, ``TwoWayConverter``,
    ``PagerScope``, a ``ProvidableCompositionLocal`` -- and at this version 53
    distinct ones appear across the catalog. None is modelled. Modelling them
    would mean inventing a representation for host state the app cannot own, and
    the failure would be a prop that accepts something meaningless.

    So a parameter this cannot type is *omitted* rather than approximated, and
    the omission is recorded. That is the difference between a component that
    is present with fewer props than Compose declares -- which fails at build
    time, loudly -- and one that silently accepts a prop meaning nothing.

    Args:
        parameter: The parameter to type.

    Returns:
        Its wire type, or None when it is not expressible.
    """
    if parameter.kind is Kind.SLOT:
        return Wire.CONTENT
    if parameter.kind is Kind.CALLBACK:
        return Wire.ACTION
    if parameter.type.startswith(UNREADABLE):
        # The dump could not read this parameter's Kotlin type. Refusing is the
        # point: the raw JVM type behind it is `long` for Dp, TextUnit and Long
        # alike, so typing it would put an integer where a dimension belongs.
        return None
    return _by_name(parameter.type.partition("<")[0])


# Every mapping beyond SCALARS in one table, so adding a family is one row
# rather than another branch -- which is the difference between a policy that
# survives a Compose release and one that needs editing each time.
FAMILIES = {
    **{name: Wire.ENUM for name in ENUMS},
    **{name: Wire.EDGES for name in EDGES},
    **{name: Wire.DIMENSION for name in SIZED},
    "Brush": Wire.BRUSH,
}


def _by_name(name: str) -> Wire | None:
    """Resolve a bare Kotlin type name to a wire type.

    Args:
        name: The simple type name, with any generic argument removed.

    Returns:
        Its wire type, or None when the type is not expressible on the wire.
    """
    if name in SCALARS:
        return SCALARS[name]
    if name in FAMILIES:
        return FAMILIES[name]
    # Alignment, Arrangement and their subclasses are enum families whose
    # members a schema entry declares itself.
    if name.startswith(("Alignment", "Arrangement")):
        return Wire.ENUM
    return None


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


def _parse(
    signature: str,
) -> tuple[str, tuple[Parameter, ...], tuple[str, ...]] | None:
    """Read one rendered signature.

    Args:
        signature: ``[@ExperimentalX ]name(a: T = default, b: U)`` as the dump
            writes it.

    Returns:
        The name, its parameters and its stability markers, or None when the
        shape is unrecognised.
    """
    text = signature.strip()
    markers = (
        tuple(_ANNOTATIONS.match(text).group(1).split())
        if _ANNOTATIONS.match(text)
        else ()
    )
    stripped = _ANNOTATIONS.sub("", text, count=1)
    match = _SIGNATURE.match(stripped)
    if match is None:
        return None
    name, body = match.group(1), match.group(2)
    parameters: list[Parameter] = []
    if body.strip():
        for prop, type_name in _PARAM.findall(body):
            declared = _DEFAULT.search(type_name) is not None
            rendered = _DEFAULT.sub("", type_name).strip()
            if not rendered:
                continue
            parameters.append(
                Parameter(
                    name=prop,
                    type=rendered,
                    kind=_classify(rendered),
                    # A Compose default means the app need not supply it, and the
                    # generated adapter omits it so Compose's own default wins.
                    # That inverts to "required" with no further judgement.
                    required=not declared,
                )
            )
    if not parameters and body.strip():
        return None
    return name, tuple(parameters), markers


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
    groups: dict[str, list[tuple[str, tuple[Parameter, ...], tuple[str, ...]]]],
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
            markers=best[2],
        )


def _plainness(signature: tuple[str, tuple[Parameter, ...], tuple[str, ...]]) -> str:
    """Return a sort key that prefers plain types over wrapper types.

    Args:
        signature: The parsed signature.

    Returns:
        A string, lower sorting first.
    """
    types = sorted({p.type for p in signature[1]})
    return "".join(sorted({t[0] for t in types}))


def _priority(signature: tuple[str, tuple[Parameter, ...], tuple[str, ...]]) -> int:
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
                groups.setdefault(parsed[0], []).append(
                    (class_name, parsed[1], parsed[2])
                )
    return {c.name: c for c in _most_crossing(groups)}


def summarise(directory: Path = DUMP_DIR) -> str:
    """Describe what the dump contains, for a human.

    Every line is a number someone might act on. An omitted count is a scope
    decision; an unread count is a bug in the dump. They are reported separately
    for exactly that reason -- lumping them together would make a tooling fault
    look like a design choice.

    Args:
        directory: Where the JSON files live.

    Returns:
        A short report.
    """
    found = composables(directory)
    slots = sum(len(c.slots) for c in found.values())
    callbacks = sum(len(c.callbacks) for c in found.values())
    omitted = sum(len(c.omitted) for c in found.values())
    unread = sum(
        1 for c in found.values() for p in c.parameters if p.type.startswith(UNREADABLE)
    )
    experimental = sum(1 for c in found.values() if c.experimental)
    required = sum(1 for c in found.values() for p in c.parameters if p.required)
    overloads = sum(1 for c in found.values() if c.overloads > 1)
    return (
        f"{len(found)} composables across {len(load(directory))} artifacts\n"
        f"  {slots} content slots, {callbacks} callbacks\n"
        f"  {required} required params, the rest have a Compose default\n"
        f"  {experimental} experimental at this version, "
        f"{len(found) - experimental} stable\n"
        f"  {omitted} props not expressible on the wire, recorded as omitted\n"
        f"  {unread} parameter types unread from metadata (a dump bug, not a scope)"
        f"\n  {overloads} names with overloads, resolved to the most-crossing"
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
