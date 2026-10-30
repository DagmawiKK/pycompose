"""The host-owned state holder a component accepts (ADR-0016, ADR-0058)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pycompose.errors import ComponentRegistryError
from pycompose.model.catalog.registry_vocabulary import STATE_KINDS


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
