# PyCompose

A Python UI library for Android. Define your app UI in Python; a Kotlin/Jetpack
Compose **Material 3** host renders it natively. The two sides exchange only
data — a pure IR contract — never objects.

> Work in progress. Phase 1 (foundation: toolchain, SSOT registry + codegen,
> CI) is underway. Roadmap: `docs/plan/13_IMPLEMENTATION_CHECKLIST.md`.

## Architecture in one line

- **Pure IR**: Python emits a deterministic canonical JSON snapshot
  (`schemaVersion`d); the host consumes sealed IR models and renders them.
- **State owned by Python**: frozen `State` in a mutable `Store`; the emitter is
  a pure `f(State) -> IRRoot`; full snapshot per change; stable node ids.
- **Boundaries enforced, not suggested**: `import-linter` (Python) + ArchUnit
  (Kotlin) are blocking; `:ir` is pure JVM (zero Compose/Android).
- **SSOT**: `schema/components.json` → codegen → sealed Kotlin models + Python
  validators + derived JSON Schema (committed, CI `--check`).

## Vocabulary & decisions

See [`GLOSSARY.md`](GLOSSARY.md) for domain terms and `docs/adr/` for locked
decisions (`AGENTS.md` mirrors them at the root).

## Developer setup

```bash
pip install -e ".[dev]"
pre-commit install
make fmt && make precommit && make test
```

## Python checks

```bash
ruff check . && ruff format --check .
mypy pycompose
bandit -ll -q -r pycompose
import-linter --config pyproject.toml   # blocking boundary gate
pytest -q
```

## Registry (single source of truth)

Edit `schema/components.json` only — never the generated files. To add a component:

1. Add its definition to `schema/components.json` (category, stability, props, children).
2. `python tools/schema/gen.py` — regenerates `schema/ir.schema.json` + `pycompose/ir/generated_validators.py`.
3. Review the diff; commit the generated artifacts alongside the registry change (they are committed, never hand-edited).
4. `python tools/schema/gen.py --check` verifies no drift — enforced by pre-commit and CI.
