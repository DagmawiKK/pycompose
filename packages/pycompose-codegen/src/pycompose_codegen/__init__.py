"""pycompose_codegen — the component catalog pipeline.

``derive`` reads the pinned Compose libraries and the review decisions under
``schema/policy/`` and writes the catalog lock; ``emit`` generates the runtime's
Python components and the host's Kotlin models, adapters and validators from it,
and each app's component slice. It runs on a developer's machine and in CI,
never on a device.
"""

__version__ = "0.1.0"
