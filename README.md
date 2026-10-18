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

### Create an app

```bash
pycompose init notes
cd notes
pycompose debug                 # build, install, verify, launch
```

The visible project is just `app/`, `resources/`, and `pycompose.toml`. The
versioned Android scaffold lives in `.pycompose/android/`; the CLI builds there
without moving your Python source. Native sources are persistent and can be
committed; its Gradle caches, generated files, and `local.properties` are ignored.
Do not delete `.pycompose/android/` as though it were a disposable cache.
Commit `.pycompose/resource-sync.json` alongside native resource outputs; it
records which files the CLI may safely update after a clone.

Use `pycompose config show` / `pycompose config set` for supported app settings.
For advanced Android customization, open `.pycompose/android/` in Android Studio,
or create a conventional root-level Android project with
`pycompose init notes --native`. Existing root-level projects continue to work
unchanged. Neither builds nor re-running `init` overwrite native customizations.

The SDK can be supplied through `ANDROID_HOME` or the native project's
`local.properties` (`.pycompose/android/local.properties` in the default layout).
Always build through the CLI so the Python source and component slice are staged.

### Work on PyCompose

```bash
pip install -e ".[dev]"
pre-commit install
npm ci             # commitlint (commit-msg hook)
brew install actionlint   # for the actionlint pre-commit hook (CI runs it too)
make fmt && make precommit && make test
```

## Python checks

```bash
ruff check . && ruff format --check .   # E/W/N = PEP 8 + pep8-naming
mypy pycompose
bandit -ll -q -r pycompose
pydoclint pycompose                     # Google-style docstrings (public API)
import-linter --config pyproject.toml   # blocking boundary gate (binary: lint-imports)
actionlint .github/workflows/*.yml      # workflow files
pytest -q
```

Commit messages are semantic (Conventional Commits) and checked by a
`commit-msg` hook ([`commitlint.config.mjs`](commitlint.config.mjs)) — no
"Phase X:" / filler subjects.

## Registry (single source of truth)

Edit `schema/components.json` only — never the generated files. To add a component:

1. Add its definition to `schema/components.json` (category, stability, props, children).
2. `python tools/schema/gen.py` — regenerates `schema/ir.schema.json` + `pycompose/ir/generated_validators.py`.
3. Review the diff; commit the generated artifacts alongside the registry change (they are committed, never hand-edited).
4. `python tools/schema/gen.py --check` verifies no drift — enforced by pre-commit and CI.
