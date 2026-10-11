# ADR-0006: Internal pipeline redesign (#7)

**Status:** Accepted
**Date:** 2026-10-11
**Deciders:** PyCompose maintainers
**Technical area:** Runtime pipeline

## Context

The #7 internal pipeline redesign was driven by correctness and robustness constraints, not by micro-optimizing an already-fast narrow case. The following requirements necessitated the change:

- Support for arbitrary finite depth.
- Ancestor cycle safety.
- Identity preservation for structural sharing.
- Deterministic release degradation.
- Fail-closed debug behavior.

Measured evidence across Mac/Ubuntu (matched before/after, phases, memory, drop workload) supports the tradeoff. Public API, wire format, and canonical bytes remain unchanged.

## Decision

Adopt the redesigned internal pipeline (#7) as the required foundation. Correctness and robustness are the primary drivers; performance is a secondary consideration. No changes to public surface or canonical serialization.

## Consequences

- **Correctness:** Pipeline safely handles deep trees, ancestor cycles, and structural sharing.
- **Behavior:** Deterministic degradation in release builds; debug behavior remains fail-closed.
- **Compatibility:** Public API, wire format, and canonical bytes unchanged.
- **Validation:** Tradeoff supported by measured evidence (Mac/Ubuntu, matched before/after, phases, memory, drop workload).
- **Readiness:** Provides a robust transformation pipeline to support component work (#8).

## References

- Existing ADRs: 0001–0005 (unidirectional state, registry SSOT/codegen, pure IR boundary, staged modules Android-first, fail-closed validation).
- #8 next work: Components, first batch — Text, Column, Row, Box, Spacer, Scaffold, FilledButton, TextField, LazyColumn.
