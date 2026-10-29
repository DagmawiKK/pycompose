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
│   ├── main.py                # app — routes, destinations and the container
│   └── notes_app/
│       ├── domain/            # What a note is and what you can do with notes.
│       ├── data/              # How notes are kept, behind the domain's Protocol.
│       ├── container.py       # The app's long-lived objects, built once.
│       ├── routes.py          # Where the app can go: the list, one note's editor.
│       ├── view_models/       # Each screen's state, intents and behaviour.
│       └── views/             # Screens: pure functions of their state.
└── tests/
    └── smoke.py               # End-to-end walk through the whole app.
```

Dependencies only ever point downwards. `views` know the state and intents of
their view model; view models know the domain and the routes they open; the
domain knows nothing above it. `main.py` wires each route to its view model and
screen.

## How the data flows

```
control → intent → view model → new state → screen(state) → snapshot → host renders
```

A control carries an intent, a typed object naming what the user asked for:

```python
Card(on_click=OpenNote(note_id=note.id), ...)
```

so one `OpenNote` intent class serves every row on screen. The host holds the
intent as data, never a Python object or a callback. A control whose event
supplies the value carries the class, or binds part of it:

```python
TextField(value=note.title, on_value_change=SetTitle.bind(note_id=note.id), ...)
```

## Navigation

Python owns the back stack. `OpenNote` pushes `EditorRoute(note_id=…)`; leaving
the editor pops it, and the system back gesture pops it too. Each screen on the
stack keeps its own view model, so the list's filter is still set when you come
back, and the list followed the repository meanwhile through
`container.listing`, a `StateFlow` of every note.

The host keeps each route only to hand it back: after process death the whole
stack comes back, each screen with its saved state. A note opened from outside
the app arrives as a deep link; `EditorRoute` is the only route allowed to.

## What it is a demo of

- **Persistence that survives process death.** Force-stop the app and relaunch it
  mid-sentence; the text is still there.
- **Per-instance bindings.** Every row and field targets the right note.
- **One-shot effects.** Creating a note asks for `haptic`; the host runs it once.
- **An app theme.** `[theme]` in `pycompose.toml` names the colours in
  `theme.json` (Material Theme Builder's export format). Views paint with theme
  roles such as `ThemeColor("onSurfaceVariant")`, so dark mode needs no code.
- **Degrading rather than crashing.** A corrupt save, a deep link naming a
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
