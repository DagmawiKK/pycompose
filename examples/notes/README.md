# Notes

A two-screen notes app written entirely in Python. No Kotlin, no Java, no XML.

Every control it puts on screen is a native Material 3 composable — `Scaffold`,
`LazyColumn`, `TextField`, `FilledButton`, `TextButton` — rendered by the Android
host. Python declares the tree; the host draws it.

## Running it

The Python lives in `app/`, which is where `pycompose init` puts it by default
(`python.source_dir = "app"`, `python.entrypoint = "main:app"`). To get a
running Android project:

```bash
pycompose init notes                       # app-focused project
cp -R examples/notes/app/. notes/app/       # drop this app in
cp -R examples/notes/overlay/resources/. notes/resources/
cp -R examples/notes/overlay/host/. notes/.pycompose/android/host/
cd notes && pycompose run                   # build, install, launch, watch edits
```

`overlay/` carries the two things this app owns outside Python: `app_name` in
`resources/strings.json` is the launcher label, and the `app_icon*` vectors in
`host/src/main/res/` draw the launcher icon — an adaptive icon whose monochrome
layer gives it a themed-icon form. Both are ordinary Android resources, so both
localize like every other string.

The host is under `.pycompose/android/` in a default project. With
`pycompose init notes --native` (or an existing root-level project), copy the
overlay's `host/.` into `notes/host/` instead. Copy directory **contents** using
the trailing `/.`; copying `app` into `app/` would leave the starter entrypoint
unchanged and put the Notes entrypoint one level too deep.

Or drive it with no device and no Gradle at all:

```bash
python examples/notes/tests/smoke.py
```

## The layout

```
notes/
├── app/                       # python.source_dir — this is the whole app
│   ├── main.py                # build() — the only thing the host calls
│   └── notes_app/
│       ├── model.py           # Note, Repository. Frozen data, no UI.
│       ├── theme.py           # Light and dark palettes.
│       ├── storage.py         # JSON in and out, degrading rather than raising.
│       ├── handlers.py        # The action references screens bind to.
│       ├── views/
│       │   ├── list_screen.py # Composable: the list of notes.
│       │   └── editor_screen.py
│       ├── view_model.py      # App state → one immutable snapshot.
│       └── actions.py         # The transitions a user can trigger.
└── tests/
    ├── harness.py             # Stands in for the Android host.
    └── smoke.py               # End-to-end walk through the whole app.
```

Dependencies only ever point downwards. `views` and `view_model` know about the
model; only `actions` knows about the view-model. `handlers.py` exists so that a
screen can bind an action without importing the module that defines it, which
would otherwise make those three modules circular.

## How the data flows

The app is a loop, and nothing else:

```
host action → Python action → new State → canonical IR snapshot → host renders
```

Each screen row binds its note's id when it is declared:

```python
.clickable(handlers.open_note.bind(id=f"n{note.id}", note_id=note.id))
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
- **Theming from a host-reported fact.** `onConfigChanged` carries dark mode,
  which a Python process cannot observe on its own, and the palette follows.
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
