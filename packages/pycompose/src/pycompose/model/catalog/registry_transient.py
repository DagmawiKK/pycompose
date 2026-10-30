"""The transient request rule type of the component registry.

A transient (ADR-0017 decisions 6-8) is a serial-numbered fire-and-forget
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
from pycompose.model.catalog.registry_vocabulary import TRANSIENT_KINDS


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
