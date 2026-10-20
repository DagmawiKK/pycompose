# PyCompose

Write Android app UIs in Python; they render as native Jetpack Compose
**Material 3**. Python declares the tree and owns the state; a Kotlin host draws
it. The two sides exchange only data — a canonical JSON snapshot one way, action
ids and payloads the other — never objects, callbacks, or reflection.

> Early development. The contract, code generation, CLI, and a curated Material 3
> component surface work end-to-end, including hot reload and signed release
> builds. The API and the component catalog will keep evolving.

## How it works

```
tap → action id + payload → Python handler → new snapshot → host renders
```

- **Pure IR.** Every change produces one canonical, `schemaVersion`ed JSON
  snapshot; the host validates it against sealed Kotlin models and renders.
- **Python owns state.** Frozen `State`/`AppState` values; one full snapshot per
  change; stable node ids keep identity across renders.
- **Pull-first.** The host sends an action, then asks for the latest snapshot.
  Python never pushes and never learns device details.
- **One worker.** A single Python thread; Compose's main thread never runs
  Python.
- **One source of truth.** A single component catalog generates the Python
  components, the Kotlin models, and the wire validators. Generated code is
  committed and never hand-edited.
- **Loud in debug, safe in release.** Snapshot validation fails closed in debug
  builds and degrades safely in release; library/schema/host version mismatches
  fail fast.
- **Boundaries enforced, not suggested.** Package layering and module purity are
  blocking checks, not conventions.

## Requirements

| | |
| --- | --- |
| Python | 3.12 or newer, plus pip |
| Java | JDK 17 |
| Android SDK | platform 37 and build tools, found via `ANDROID_HOME` or the project's `local.properties` |
| Device | any API 24+ device or emulator (`arm64-v8a` or `x86_64`) |
| Network | first build only: Gradle, Maven, and Chaquopy artifacts |

## Install

From a checkout:

```bash
git clone https://github.com/DagmawiKK/pycompose
cd pycompose
pip install .
```

For work on the framework itself, install the dev extras instead:
`pip install -e ".[dev]"`.

## Quick start

```bash
pycompose init notes     # scaffold a project
cd notes
pycompose debug          # build, install, launch — once
pycompose run            # the same, plus hot reload for .py and resources/
```

No device attached? `pycompose build apk` (or `pycompose release apk`)
packages without installing.

`init` lays out a project you can open in a text editor; there is no Kotlin or
XML to touch:

| Path | What it is |
| --- | --- |
| `app/` | the app's Python source (entrypoint `main:app` by default) |
| `resources/` | strings, drawables, fonts — synced into the host |
| `pycompose.toml` | identity, version, Python requirements, permissions, signing, extensions |
| `.pycompose/android/` | the versioned Android scaffold the CLI builds in — commit it |

An app is one `App` in the entry module. Here is a counter, in full:

```python
"""A counter: state, one action, one view."""

from typing import TypedDict

from m3 import Button, Column, Modifier, Text
from pycompose import Registry
from pycompose.core import Node
from pycompose.state import App, AppState


class Session(AppState):
    """What this app remembers across process death."""

    count: int = 0


class Tapped(TypedDict):
    """The tap carries no event fields; the command is the whole message."""


actions = Registry()


@actions
def increment(session: Session, payload: Tapped) -> Session:
    """Add one to the count."""
    return session.evolve(count=session.count + 1)


def view(session: Session) -> Node:
    """Draw the count and the button that moves it."""
    return Column(
        id="root",
        modifier=Modifier().padding(24),
        children=[
            Text(id="count", text=f"Tapped {session.count} times"),
            Button(
                id="tap",
                text="Tap me",
                on_click=actions.increment.bind(id="tap"),
            ),
        ],
    )


app = App(state=Session, view=view)
```

App code imports `m3`; the build generates that package from the components the
source references, so an app ships what it uses and nothing else.

A complete two-screen app — persistence, navigation, effects, theming — lives
in `examples/notes`.

## What an app declares

**`App`** — the entry object the session discovers. It takes the shell seed, the
view, an optional container factory, and the name of the shell field mirroring
the host's route.

**`AppState`** — the shell that survives process death: route, draft text,
appearance. Subclasses are frozen dataclasses; their codec is derived from the
annotations, and unreadable or foreign saved bytes fall back to the seed, so a
corrupt save starts clean instead of crashing.

**Actions** — a `Registry` turns a decorated function into both the definition
and the thing a screen binds to. The first parameter is the shell, the second a
`TypedDict` payload whose fields become the wire contract:

```python
class NoteId(TypedDict):
    note_id: int


@actions
def open_note(session: Session, payload: NoteId) -> Session:
    ...


Button(
    id="open",
    text="Open",
    on_click=actions.open_note.bind(id="open", note_id=7),
)
```

Extra keyword-only parameters are resolved from the app's container by name. The
runtime discovers the registry by the module-level name `actions` (lowercase).

**Effects** — a handler returns the next shell, or `respond(shell, *effects)` to
ask the host for something one-shot: `navigate`, `finish`, `haptic`, `toast`,
`openUrl`. Effects run once, in order, only for a snapshot that changed.

**Lifecycle** — inbound host events reach Python as actions too: `onResume`,
`onPause`, `onBackRequested`, `onRouteChanged` (route payload), and
`onConfigChanged` (orientation, dark mode, locale, density).

**Repositories and background work** — `pycompose.repository` stores documents
atomically on disk, outside the saved-state budget. `pycompose.async_task.run`
hands blocking work to a bounded executor and delivers the result back as an
ordinary action, so the worker never freezes behind a request.

**Modifiers** — `Modifier()` chains `padding`, `size`, `fill_max_width`, `clip`,
`background`, `clickable`, and window-inset padding.

## Components

87 Material 3 components. `*` marks experimental entries.

| Category | Components |
| --- | --- |
| Typography | `Text` |
| Layout and surfaces | `Box`, `Column`, `Row`, `Scaffold`, `Spacer`, `Surface`, `Card`, `ElevatedCard`, `OutlinedCard`, `PullToRefreshBox`, `VerticalDragHandle` |
| App bars | `TopAppBar`\*, `CenterAlignedTopAppBar`\*, `MediumTopAppBar`\*, `LargeTopAppBar`\* |
| Buttons | `Button`, `ElevatedButton`, `OutlinedButton`, `FilledTonalButton`, `TextButton`, `IconButton`, `FilledIconButton`, `FilledIconToggleButton`, `FilledTonalIconButton`, `FilledTonalIconToggleButton`, `IconToggleButton`, `OutlinedIconButton`, `OutlinedIconToggleButton`, `FloatingActionButton`, `LargeFloatingActionButton`, `ExtendedFloatingActionButton` |
| Selection and input | `Checkbox`, `TriStateCheckbox`, `RadioButton`, `Switch`, `Slider`\*, `TextField`, `OutlinedTextField`, `AssistChip`, `ElevatedAssistChip`, `FilterChip`, `ElevatedFilterChip`, `SuggestionChip`, `ElevatedSuggestionChip`, `InputChip` |
| Navigation and drawers | `NavigationBar`, `NavigationBarItem`, `NavigationRail`, `NavigationRailItem`, `ShortNavigationBar`, `ShortNavigationBarItem`, `WideNavigationRail`, `WideNavigationRailItem`, `ModalWideNavigationRail`, `NavigationSuiteScaffold`, `NavigationSuiteItem`, `NavigationDrawerItem`, `ModalNavigationDrawer`, `ModalDrawerSheet`, `DismissibleNavigationDrawer`, `DismissibleDrawerSheet`, `PermanentNavigationDrawer`, `PermanentDrawerSheet`, `Tab`, `LeadingIconTab`, `SecondaryTabRow`, `PrimaryTabRow`, `PrimaryScrollableTabRow`, `SecondaryScrollableTabRow` |
| Overlays and status | `ModalBottomSheet`\*, `SnackbarHost`, `Snackbar`, `AlertDialog`, `BasicAlertDialog`\*, `DropdownMenu`, `DropdownMenuItem`, `Badge`, `BadgedBox`, `CircularProgressIndicator`, `LinearProgressIndicator`\* |
| Lists | `LazyColumn`, `ListItem` |
| Media and dividers | `Icon`, `Image`, `HorizontalDivider`, `VerticalDivider` |

## CLI

| Command | What it does |
| --- | --- |
| `pycompose init <name> [--native]` | Scaffold a project; `--native` keeps Android sources at the root |
| `pycompose run [--device <serial>]` | Build, install, launch, and watch `.py` and `resources/` for hot reload |
| `pycompose debug [--no-launch]` | One build-install-launch pass, no watcher |
| `pycompose build [apk\|aab] [--release]` | Package through the project's Gradle wrapper |
| `pycompose install [--release] [--launch]` | Install a built APK and verify the installed bytes match the artifact |
| `pycompose release [apk\|aab] [--install]` | Build a signed release artifact |
| `pycompose config show` / `set <key> <value>` | Read or rewrite `label`, `application_id`, `version_name`, `version_code` |
| `pycompose sync [--check]` | Sync named resources into the host; `--check` reports drift only |
| `pycompose doctor` | Report Android toolchain and schema compatibility |
| `pycompose validate <file>` | Validate IR JSON against the registry and wire schema |
| `pycompose stubs <path>` | Print optional module stubs from a project's declarations without importing app code |
| `pycompose extensions plan` / `evidence` | Check extension requirements without importing them; `evidence` prints observed scenario evidence |

Release signing reads `[signing]` from `pycompose.toml` and the passwords from
the `PYCOMPOSE_STORE_PASSWORD` and `PYCOMPOSE_KEY_PASSWORD` environment
variables.

## Extensions

Normal Python libraries stay normal Python libraries. Optional extensions add
owned execution and lifecycle coordination. Append to `pycompose.toml`:

```toml
[extensions]
definitions = ["builtin:httpx", "builtin:sqlite"]

[android]
permissions = ["android.permission.INTERNET"]
```

`pycompose extensions plan` checks requirements without importing the
integrations. Builds install the declared Python requirements and stage only the
selected recipes; permission choices feed a generated manifest while your native
edits stay intact. HTTPX and SQLite are reference recipes; app code uses them as
ordinary libraries.

## Development

```bash
pip install -e ".[dev]"
pre-commit install
npm ci                                  # commit-message linting
make fmt && make precommit && make test
```

Commit messages follow Conventional Commits. The component catalog is the single
source of truth: components are registered, then the generated artifacts
(Python components, Kotlin models, validators, JSON schema) are regenerated and
committed — never hand-edited. A new package or boundary comes with its contract
in the same change.

## License

MIT. See [LICENSE](LICENSE).
