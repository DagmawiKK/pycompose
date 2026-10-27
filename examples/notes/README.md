# Notes

A two-screen notes app written entirely in Python. No Kotlin, no Java, no XML.

Every control it puts on screen is a native Material 3 composable — `Scaffold`,
`LazyColumn`, `TextField`, `FilledButton`, `TextButton` — rendered by the Android
host. Python declares the tree; the host draws it.

## Running it

The example is a complete project: `pycompose.toml`, the Python in `app/`, its
strings in `resources/`, and its launcher icon as one SVG, `icon.svg`. There is
no Android folder to copy or edit. Every build generates the Android project
into `.pycompose/android/` from those files (plan 31 §21), so upgrading
PyCompose changes nothing here.

```bash
cd examples/notes
pycompose run          # generate, build, install, launch, watch edits
```

`[app] icon` names the SVG, drawn on the adaptive icon's 108-unit grid, and
`icon_background` is its background colour. The same artwork becomes the themed
icon's monochrome layer and the legacy icon for older devices.
`pycompose explain host/src/main/res/drawable/app_icon.xml` says which keys
produced any generated file.

Or drive it with no device and no Gradle at all:

```bash
python examples/notes/tests/smoke.py
```

## The layout

```
notes/
├── app/                       # python.source_dir — this is the whole app
│   ├── main.py                # app — the entry object the session runs
│   └── notes_app/
│       ├── domain/            # What a note is and what you can do with notes.
│       ├── data/              # How notes are kept, behind the domain's Protocol.
│       ├── container.py       # The app's long-lived objects, built once.
│       ├── state.py           # Session, the shell that survives process death.
│       ├── theme.py           # Light and dark palettes.
│       ├── actions.py         # The transitions a user can trigger.
│       ├── views/
│       │   ├── list_screen.py # Composable: the list of notes.
│       │   └── editor_screen.py
│       └── view_model.py      # Shell plus repository → one screen.
└── tests/
    ├── harness.py             # Stands in for the Android host.
    └── smoke.py               # End-to-end walk through the whole app.
```

Dependencies only ever point downwards. `actions` knows the domain and the
session shell; `views` import the handlers they bind; `view_model` composes the
views. Nothing points back up, so no screen needs a registry threaded into it.

## How the data flows

The app is a loop, and nothing else:

```
host action → Python action → new State → canonical IR snapshot → host renders
```

Each screen row binds its note's id when it is declared:

```python
Card(on_click=open_note.with_args(note_id=note.id), ...)
```

so one `open_note` handler serves every row on screen. The host holds an id and a
number — never a Python object, never a callback.

## One naming rule worth knowing

The runtime discovers an app's action registry by the module-level name **`actions`**
— lowercase, in the entrypoint module:

```python
actions = Actions(new_note, open_note, ...)   # in notes_app/actions.py
```

Name it anything else — `ACTIONS`, say — and the registry comes up **empty**. Every
binding the snapshot publishes then fails validation and the app starts to a blank
screen with an error most people will misread. `main.py` re-exports it as `actions`
for exactly this reason, and `tests/test_notes_example.py` drives the real
`RuntimeSession` to prove it.

## Navigation, and how it differs from Compose

`NavController` swaps which composable renders while the ViewModel and repository
survive untouched. PyCompose has no retained ViewModel: the `navigate` effect
restarts the Python session with the new route, so the view-model is **rebuilt**
on every screen change.

Nothing is lost, because everything a transition produced — including half-typed
text — lives in `State.data`, which the host keeps in its `SavedStateHandle` and
hands straight back to `build`:

```python
def build(*, route="notes", restore="") -> State: ...
```

The route travels in the app's data too, because an action still needs to know
which screen it is rendering a follow-up snapshot for. The host's `route` always
wins over the saved one: it is the authority, restored from its own state.

The cost is one full re-emit per navigation. That is the host contract's doing.
The honest fix is a navigation stack in the ViewModel so a route change swaps the
screen without rebuilding the session — which is library work, not something an
app can work around.

## What it is a demo of

- **Persistence that survives process death.** Force-stop the app and relaunch it
  mid-sentence; the text is still there.
- **Per-instance bindings.** Every row and field targets the right note.
- **One-shot effects.** Creating a note asks for `haptic` and `navigate`; the
  host runs them once, in order, only for a snapshot that actually changed.
- **An app theme.** `[theme]` in `pycompose.toml` names the colours in
  `theme.json` (Material Theme Builder's export format). Views paint with theme
  roles such as `ThemeColor("onSurfaceVariant")`, so dark mode needs no code.
- **Degrading rather than crashing.** A corrupt save, a detail route naming a
  deleted note, a keystroke for a note you already left — all handled, none fatal.

## Limitations worth knowing

The component registry is deliberately small, and the gaps show:

- **No `TopAppBar`, `Card` or `Icon`.** The screens compose what they can from
  `Column`, `Row`, `Text` and `TextField`.
- **No `weight`.** Layout uses `fill_max_width` fractions, so a row with a button
  next to a growing label carries a magic number rather than a constraint.
- **`TextField` is single-line.** A long note edits in one field.
- **No background colour per node.** Only `Scaffold` takes a container colour, so
  rows have no card surface behind them.
- **No store adapter.** Data round-trips through `SavedStateHandle`, which is a
  `Bundle` with a size budget. Fine for notes, wrong for thousands of them.
