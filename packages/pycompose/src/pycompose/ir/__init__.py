"""Moved to :mod:`pycompose.wire`; this name works for one release."""

from pycompose._moved import forward

forward(
    __name__,
    "pycompose.wire",
    globals(),
    submodules={
        "actions": "pycompose.wire.actions",
        "bindings": "pycompose.wire.bindings",
        "data": "pycompose.wire.data",
        "echoes": "pycompose.wire.echoes",
        "effects": "pycompose.wire.effects",
        "emitter": "pycompose.wire.emitter",
        "host": "pycompose.wire.host",
        "model": "pycompose.wire.model",
        "patch": "pycompose.wire.patch",
        "serializer": "pycompose.wire.serializer",
        "streams": "pycompose.wire.streams",
        "validator": "pycompose.wire.validator",
        "validator_walk": "pycompose.wire.validator_walk",
    },
)
