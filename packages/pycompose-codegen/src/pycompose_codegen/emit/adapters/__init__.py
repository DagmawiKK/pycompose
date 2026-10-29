"""The Kotlin adapters derived from the catalog, one module per job.

``assemble`` writes each adapter and the file holding them; ``eligibility``
decides which components get one; ``props``, ``state`` and ``slots`` render a
prop, a host-owned holder and a child path into the call; ``policy`` holds the
wire-to-Kotlin tables they share and ``imports`` the imports an adapter needs.
"""
