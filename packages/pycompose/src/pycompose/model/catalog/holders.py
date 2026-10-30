"""The host-owned state a component accepts: a holder, and transient requests.

A holder (ADR-0016, ADR-0058) is the native state object the host keeps per
node. A transient (ADR-0017 decisions 6-8) is a serial-numbered fire-and-forget
request beside the state rail: the host remembers the last serial it handled
under the node's identity, fulfils a request whose serial it has not seen,
and reports the fulfilled serial back as an occurrence action, so an
identical re-rendered snapshot stays a no-op while a deliberate repeat of
identical content is a new serial.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pycompose.errors import ComponentRegistryError
from pycompose.model.catalog.vocabulary import STATE_KINDS, TRANSIENT_KINDS


@dataclass(frozen=True, slots=True)
class StateRule:
    """The host-owned state holder a component accepts.

    The holder is the host's: it is created per stable node id, so pulling a
    snapshot re-renders the tree without recreating state a gesture is already
    moving. Python states the desired value in the snapshot; the host drives
    the holder towards it and reports settled changes back as actions, rather
    than both sides writing the same state.

    Attributes:
        native: Native parameter the remembered holder fills.
        kind: State family, naming the host's create/drive/report logic.
        value: Prop carrying the desired state; absent drives nothing.
        report: ActionId prop reporting settled changes; absent reports nothing.
        dismiss: Native parameter through which the component announces a
            dismissal it has already carried out, if it has one.
        derived: Kind ``properties``: the holder, factory and properties the
            pin implies, each property its own value and report (ADR-0058).
    """

    native: str
    kind: str
    value: str | None = None
    report: str | None = None
    dismiss: str | None = None
    derived: Mapping[str, object] | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, object], *, where: str) -> StateRule:
        """Build a :class:`StateRule` from raw JSON.

        Args:
            data: The raw state object.
            where: Human-readable location for error messages.

        Returns:
            The parsed state rule.

        Raises:
            ComponentRegistryError: If the state object is malformed.
        """
        native = data.get("native")
        if not isinstance(native, str) or not native:
            raise ComponentRegistryError(f"{where}: 'native' must be a name")
        kind = data.get("kind")
        if kind == "properties":
            derived = {k: data.get(k) for k in ("holder", "factory", "properties")}
            if not all(derived.values()):
                raise ComponentRegistryError(
                    f"{where}: name holder, factory, properties"
                )
            return cls(native=native, kind="properties", derived=derived)
        if not isinstance(kind, str) or kind not in STATE_KINDS:
            raise ComponentRegistryError(
                f"{where}: unknown state kind {kind!r}; vocabulary: "
                + ", ".join(STATE_KINDS)
            )
        names: dict[str, str] = {}
        for field_name in ("value", "report"):
            prop = data.get(field_name)
            if not isinstance(prop, str) or not prop:
                raise ComponentRegistryError(
                    f"{where}: {field_name!r} must name a prop"
                )
            names[field_name] = prop
        dismiss = data.get("dismiss")
        if dismiss is not None and (not isinstance(dismiss, str) or not dismiss):
            raise ComponentRegistryError(f"{where}: 'dismiss' must be a name")
        return cls(
            native=native,
            kind=kind,
            value=names["value"],
            report=names["report"],
            dismiss=dismiss if isinstance(dismiss, str) else None,
        )

    def to_mapping(self) -> dict[str, object]:
        """Render back to the catalog lock state shape.

        Returns:
            A JSON-ready dict.
        """
        result: dict[str, object] = {"native": self.native, "kind": self.kind}
        if self.derived is not None:
            return {**result, **self.derived}
        result.update(value=self.value, report=self.report)
        if self.dismiss is not None:
            result["dismiss"] = self.dismiss
        return result


@dataclass(frozen=True, slots=True)
class TransientRule:
    """A host-fulfilled transient request this component accepts.

    Attributes:
        native: Native parameter the remembered holder fills.
        kind: Transient family, naming the host's remember/fulfil/report
            logic.
        serial: Integer prop carrying the request serial; absent requests
            nothing, an unchanged serial is a no-op, a bumped one fulfils.
        occurrence: ActionId prop reporting the fulfilled serial back.
    """

    native: str
    kind: str
    serial: str
    occurrence: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, object], *, where: str) -> TransientRule:
        """Build a :class:`TransientRule` from raw JSON.

        Args:
            data: The raw transient object.
            where: Human-readable location for error messages.

        Returns:
            The parsed transient rule.

        Raises:
            ComponentRegistryError: If the transient object is malformed.
        """
        native = data.get("native")
        if not isinstance(native, str) or not native:
            raise ComponentRegistryError(f"{where}: 'native' must be a name")
        kind = data.get("kind")
        if not isinstance(kind, str) or kind not in TRANSIENT_KINDS:
            raise ComponentRegistryError(
                f"{where}: unknown transient kind {kind!r}; vocabulary: "
                + ", ".join(sorted(TRANSIENT_KINDS))
            )
        names: dict[str, str] = {}
        for field_name in ("serial", "occurrence"):
            prop = data.get(field_name)
            if not isinstance(prop, str) or not prop:
                raise ComponentRegistryError(
                    f"{where}: {field_name!r} must name a prop"
                )
            names[field_name] = prop
        return cls(
            native=native,
            kind=kind,
            serial=names["serial"],
            occurrence=names["occurrence"],
        )

    def to_mapping(self) -> dict[str, object]:
        """Render back to the catalog lock transient shape.

        Returns:
            A JSON-ready dict.
        """
        return {
            "native": self.native,
            "kind": self.kind,
            "serial": self.serial,
            "occurrence": self.occurrence,
        }
