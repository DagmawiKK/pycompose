# PyCompose

Write Android apps in Python; they render as native Jetpack Compose
**Material 3**. Python declares the screen and owns the state; a Kotlin host
draws it. The two sides exchange only data — a canonical JSON snapshot one way,
intents and their fields the other — never objects, callbacks, or reflection.

There are two ways to write an app, and they share everything underneath:

- **Blocks** — components, events and plain functions. Declare the screen in a
  `with` block, connect a button to a function, and the function's result fills
  the outputs. The quickest way from an idea, an API or a model to an app.
- **View models** — the full-control route, shaped like Android's architecture
  guidance: each screen's view model owns its state, controls send typed
  intents, and screens are drawn from about 130 native components.

> Early development. The contract, the component compiler, the CLI and about 130
> Material 3 and foundation components work end to end, including hot reload, a
> prebuilt dev client and signed release builds. The API will keep evolving.

## How it works

```
tap → intent + fields → view model → new state → screen(state) → host renders
```

- **Pure IR.** Every change produces one canonical, `schemaVersion`ed JSON
  snapshot; the host validates it against sealed Kotlin models and renders.
- **Python owns state.** Each screen's view model holds a frozen `AppState`;
  one full snapshot per change; stable node ids keep identity across renders.
- **Pull-first.** The host sends an action, then asks for the latest snapshot.
  Python never pushes and never learns device details.
- **One loop thread.** Python state lives on one event-loop thread; blocking
  and CPU work go to pools. Compose's main thread never runs Python.
- **Derived from Compose itself.** A compiler reads the pinned Compose libraries
  and derives each component's props, slots and defaults, the value types they
  take, the state holders behind controlled components, and the modifiers a
  parent's scope offers its children. The result is a committed lock that must
  reproduce from the pin; Python components, Kotlin adapters and wire
  validators are generated from it and never hand-edited.
- **Controlled without a fight.** A stated value drives the native holder only
  when it changes, and each value the user settles on is reported once, so
  Python can own a picker's time or a sheet's position without overriding a
  gesture in progress.
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

`pycompose setup` installs the pinned JDK and Android SDK if you have neither.

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
pycompose init hello     # scaffold a project, starting from blocks
cd hello
pycompose debug          # build, install, launch — once
pycompose run            # the same, plus hot reload for .py and resources/
```

`pycompose init hello --template viewmodel` starts from a view model instead.

No device attached? `pycompose build apk` (or `pycompose release apk`)
packages without installing, and `pycompose check` finds what a build or the
store would refuse without running either.

**Skip Gradle while you iterate.** `pycompose dev-client` builds, once per
PyCompose version, a debug host that carries the whole catalog. After that,
`pycompose run --dev-client` installs it and serves your app to it: edits to
`.py` files and resources reload on the device with no Android build at all. A
dev client built from an older framework is refused with the command that
rebuilds it.

`init` lays out a project you can open in a text editor; there is no Kotlin or
XML to touch:

| Path | What it is |
| --- | --- |
| `app/` | the app's Python source (entrypoint `main:app` by default) |
| `resources/` | strings, drawables, fonts — synced into the host |
| `pycompose.toml` | identity, version, Python requirements, theme, permissions, signing |
| `.pycompose/` | the Android project, generated from the app on every build; ignored by git |

`pycompose prebuild` shows what the generated project would change, and
`pycompose explain <file>` names the settings that produced a generated file.

The app `init` writes, in full:

```python
import pycompose.blocks as pc


def greet(name: str) -> str:
    return f"Hello, {name.strip() or 'world'}!"


with pc.Blocks() as app:
    name = pc.Textbox(label="Your name")
    greeting = pc.Markdown("Type your name and tap Greet.")
    pc.Button("Greet").click(greet, inputs=name, outputs=greeting)
```

Change the text while `pycompose run` is watching and the phone shows it on save.

## Building with blocks

Every component and layout created inside `with pc.Blocks() as app:` joins the
screen in the order the code creates it. Each is drawn from native Material 3
components, so the app looks and behaves like any Compose app.

| Kind | Components |
| --- | --- |
| Text | `Textbox`, `Number`, `Markdown` |
| Choices | `Checkbox`, `Radio`, `Dropdown`, `Slider` |
| Results | `Image`, `Gallery`, `Label` (a classifier's top labels as bars), `JSON`, `Chatbot` |
| Files | `Image(interactive=True)`, `File`, `UploadButton` |
| Actions | `Button` |
| Layout | `Row` (wraps to the screen's width), `Column`, `Tabs` with `Tab`, `Accordion` |

Every component takes `label`, `visible` and, where it makes sense,
`interactive`; a component that is the output of a function shows a progress
bar while the function runs.

**Events** connect a component to a function. `inputs` are the components the
function reads, in order; `outputs` the ones its result fills — one value per
output, a tuple for several:

```python
pc.Button("Forecast").click(forecast, inputs=[city, days], outputs=[now, ahead])
city.change(suggest, inputs=city, outputs=hints)      # on every edit
upload.upload(describe, inputs=upload, outputs=text)  # on every file picked
```

- A plain function runs on a thread pool, so a slow network call never freezes
  the screen; an `async def` one runs on the app's loop.
- **A function that yields streams:** each value it yields is shown as it
  arrives, which is how a chat reply appears word by word.
- An event that fires again before its last run returned cancels that run, so
  only the latest result is shown.
- An exception becomes a toast with its message; the outputs keep their values.

**Shortcuts** build the usual app around one function:

```python
app = pc.Interface(translate, inputs=pc.Textbox(label="English"), outputs=pc.Textbox(label="French"))
app = pc.ChatInterface(reply)   # reply(message, history) returns or yields text
```

Chat history is a list of `{"role": "user" | "assistant", "content": text}`
messages, the shape chat model APIs take, so a function can pass it straight on.

**Pictures** go in an `Image` or `Gallery` output as bytes, a file path, or a
PIL image. The host loads nothing from the network: download in your function
and return the bytes. An interactive `Image`, a `File` or an `UploadButton`
opens the system picker — the photo picker for images — with no permission
prompt, and the function receives the picked file's path.

The examples are complete apps, each a single file:

| Example | What it shows |
| --- | --- |
| `examples/weather` | two HTTP calls behind one button; tabs for the results |
| `examples/chat` | a chat with any OpenAI-compatible model, the reply streaming in |
| `examples/dogs` | downloading photos and showing them in an image and a gallery |
| `examples/photos` | picking a photo and editing it with Pillow on every change |
| `examples/notes` | the view-model route: two screens, SQLite, navigation, theming |

Each one runs with `cd examples/<name> && pycompose debug`.

## Building with view models

When an app outgrows one screen of components — several screens, its own
navigation, native components beyond the blocks set — it is written as view
models. Here is a counter, in full:

```python
"""A counter: one view model, one intent, one screen."""

from m3 import Button, Column, Modifier, Text
from pycompose.app import App, Destination, Intent, ViewModel
from pycompose.core import Node
from pycompose.state import AppState


class Counter(AppState):
    """What the screen shows; saved across process death."""

    count: int = 0


class Increment(Intent):
    """Add one to the count."""


class CounterViewModel(ViewModel[Counter]):
    def __init__(self) -> None:
        super().__init__(Counter())

    def on_intent(self, intent: Intent) -> None:
        if isinstance(intent, Increment):
            self.state = self.state.evolve(count=self.state.count + 1)


def screen(state: Counter) -> Node:
    """Draw the count and the button that moves it."""
    return Column(
        modifier=Modifier().padding(24),
        children=[
            Text(text=f"Tapped {state.count} times"),
            Button(text="Tap me", on_click=Increment()),
        ],
    )


app = App(start=Destination(lambda _container, _route: CounterViewModel(), screen))
```

App code imports `m3`; the build generates that package from the components the
source references, so an app ships what it uses and nothing else.

### Structuring a larger app

An app with several screens follows Android's [guide to app
architecture](https://developer.android.com/topic/architecture): a data layer
behind the domain, a UI layer of view models and screens, and dependencies
wired by hand in one place. `examples/notes` is built this way; the excerpts
below are from it.

```
app/
  main.py                  # the App: routes → destinations, the container
  notes_app/
    domain/                # models and use cases; imports nothing above it
    data/                  # repositories behind the domain's Protocol
    container.py           # the app's long-lived objects, built once
    routes.py              # where the app can go
    view_models/           # each screen's state, intents and behaviour
    views/                 # screens: pure functions of their state
```

**Domain** — entities are frozen dataclasses, and what the domain needs from
storage is a `Protocol`, so any implementation satisfies it structurally.
Use cases hold the repository; nothing above them ever sees it:

```python
@dataclass(frozen=True)
class Note:
    id: int
    title: str = ""
    body: str = ""


class NotesRepo(Protocol):
    def load(self) -> list[Note]: ...
    def insert(self, note: Note) -> None: ...
    def update(self, note: Note) -> None: ...
    def delete(self, note_id: int) -> None: ...


class Notes:
    """Everything the app can do with notes, with the storage already bound."""

    def __init__(self, notes: NotesRepo, changed=lambda _notes: None) -> None: ...
    def create(self, title: str = "", body: str = "") -> int: ...
    def rename(self, note_id: int, title: str) -> None: ...
```

**Data** — `SqliteNotesRepo` implements `NotesRepo` on SQLite, one row per
note. Its statements run on the session's storage thread with
`to_thread("storage", ...)`, in order, so the loop never waits on the disk.

**Container** — Google's manual dependency injection: one object holds the
app's long-lived dependencies, built once per session. It is the only place
that names a storage backend, and a `StateFlow` lets screens follow the data:

```python
class AppContainer:
    def __init__(self, repo: NotesRepo) -> None:
        self.notes = Notes(repo, changed=self._publish)
        self.listing: StateFlow[tuple[Note, ...]] = StateFlow(tuple(self.notes.list()))

    def _publish(self, notes: list[Note]) -> None:
        self.listing.value = tuple(notes)


def build() -> AppContainer:
    return AppContainer(SqliteNotesRepo())
```

**Routes and destinations** — a route is a typed destination; each opens a view
model built from the container, drawn by its screen. Python owns the back stack
and saves every entry, so process death restores all of it:

```python
class NotesRoute(Route):
    """The list of every note."""


class EditorRoute(Route):
    note_id: int


app = App(
    start=NotesRoute(),
    destinations={
        NotesRoute: Destination(
            lambda c, _route: ListViewModel(c.notes, c.listing), list_screen
        ),
        EditorRoute: Destination(
            lambda c, route: EditorViewModel(c.notes, route.note_id), editor_screen
        ),
    },
    container=build,
    deep_links=frozenset({EditorRoute}),
)
```

**View models** — state the screen can rebuild is marked `Loaded[...]`: it is
reloaded when the view model is built and never saved, since Android's saved
state is limited to kilobytes. A view model follows the container's `StateFlow`
for as long as it lives, so an edit made on the editor is on the list when the
user comes back:

```python
class ListState(AppState):
    notes: Loaded[tuple[Note, ...]] = ()   # from storage, never saved
    previews: bool = True                  # small UI state, saved


class OpenNote(Intent):
    note_id: int


class ListViewModel(ViewModel[ListState]):
    def __init__(self, notes: Notes, listing: StateFlow[tuple[Note, ...]]) -> None:
        super().__init__(ListState(notes=listing.value))
        self._notes = notes
        self._listing = listing
        self.launch(self._follow())

    async def _follow(self) -> None:
        async for notes in self._listing:
            self.state = self.state.evolve(notes=notes)

    def on_intent(self, intent: Intent) -> None:
        match intent:
            case OpenNote(note_id=note_id) if self._notes.get(note_id) is not None:
                self.navigate(Push(EditorRoute(note_id=note_id)))
```

**Screens** — a pure function of the view model's state, built from native
components. A list is data: `LazyColumn` asks Python only for the rows on
screen, and each row's intent carries the note it stands for:

```python
def list_screen(state: ListState) -> Node:
    return Scaffold(
        content=LazyColumn(
            items=list(state.notes),
            key=lambda note: f"row_{note.id}",
            item=lambda note: Card(
                on_click=OpenNote(note_id=note.id),
                children=[Text(text=note.label, style="titleMedium")],
            ),
        ),
    )
```

**Tests** — because the use cases see only the `Protocol`, an in-memory
repository runs every one of them without a disk, and `AppDriver` walks the
whole app, screen by screen, as the host would:

```python
notes = Notes(MemoryNotesRepo([Note(1, "Milk")]))
note_id = notes.create("Eggs")
assert notes.get(note_id).title == "Eggs"

with AppDriver(Path("examples/notes")) as app:
    app.click(type="FloatingActionButton")
    app.edit("Groceries", label="Title")
```

The full app, with an editor, filters, a bottom sheet and theming, is in
`examples/notes`.

### What an app declares

**`App`** — the entry object the session discovers. It takes where the app
starts, a `Destination` per route, an optional container factory (Google's
manual dependency injection: built once per session and handed to each view
model's factory), and the routes the host may open from outside.

**`ViewModel`** — one screen's state and behaviour. Its state is an `AppState`:
a frozen dataclass whose codec is derived from its annotations. The state is
saved for process death, except fields marked `Loaded[...]`, which the view
model refills from its repository; an unreadable save starts clean instead of
crashing.

**Intents** — what a control asks its screen to do. An intent is a typed
dataclass; a control takes an instance (every field bound), the class (every
field supplied by the event), or `Intent.bind(...)` (some of each):

```python
class OpenNote(Intent):
    note_id: int


Card(on_click=OpenNote(note_id=7), ...)
TextField(value=note.title, on_value_change=SetTitle.bind(note_id=note.id))
```

State a target rather than a change (`SetExpanded(id, True)`, not `Toggle(id)`),
so a duplicate or a stale tap still does the right thing.

**Routes** — a `Route` is a typed destination, such as `EditorRoute(note_id=4)`.
A view model calls `self.navigate(Push(route))`, `Replace(route)` or `Pop()`;
Python owns the back stack, and every entry's state is saved, so process death
restores the whole stack.

**Identity** — a node needs no `id`. One declared without one is keyed by the
line of code that declares it, so a conditional before it never shifts its
identity. Only things declared in a loop that carry an intent, and composables
called in a loop, need an `id` to survive a reorder.

**Effects** — `self.emit(...)` asks the host for something one-shot: `Toast`,
`Haptic`, `OpenUrl`, `PickFile` (answered by `on_file_picked(request, path)`). Effects run at most once, in order; anything that must
happen belongs in state instead.

**Lifecycle** — `on_back` (return True to keep the screen), `on_resume` and
`on_pause` reach the view model on top; `on_trim_memory(level)` reaches every
screen on the stack when Android asks for memory back.

**Background work** — `self.launch(coroutine)` runs work until it ends or the
view model is cleared, and returns its task, so a newer request can cancel the
one it supersedes. Blocking calls go to a pool with
`await to_thread("io", fn, *args)` and computation with
`await to_thread("cpu", fn, *args)`; the screen stays live meanwhile.
`pycompose.repository` stores documents atomically on disk, outside the
saved-state budget.

**Controlled components** — a component whose native state lives in a holder
(a picker, a slider, a drawer, a sheet, a tooltip) takes the value as a prop
and reports changes through an `on_<value>_change` intent:

```python
TimePicker(
    hour=state.hour,
    minute=state.minute,
    on_hour_change=SetHour,
    on_minute_change=SetMinute,
)
```

Omit a value to leave it to the user; set it to move the native control.

**Modifiers** — `Modifier()` chains `padding`, `size`, `fill_max_width`, `clip`,
`background`, `clickable`, window-inset padding and accessibility `semantics`.
It also offers the modifiers a parent's scope declares, which a child wears
only inside that parent: `weight` in a `Row` or `Column`, `row_align`,
`column_align` and `box_align`, `match_parent_size`, and `menu_anchor` for the
field that opens an `ExposedDropdownMenuBox`:

```python
Row(
    children=[
        Text(text="Name", modifier=Modifier().weight(1)),
        Text(text="Value", modifier=Modifier().weight(2)),
    ]
)
```

One worn outside such a parent is reported by the host rather than ignored.

## Native components

What view-model screens are drawn from, and what blocks components are built
from: 134 Material 3 and foundation components, 145 counting the overloads a
component reaches through its own name. `*` marks experimental entries.

| Category | Components |
| --- | --- |
| Typography | `Text`, `TextAnnotatedString`, `BasicText`, `Label`\* |
| Layout and surfaces | `Box`, `Column`, `Row`, `Scaffold`, `BottomSheetScaffold`\*, `Spacer`, `Surface`, `Card`, `ElevatedCard`, `OutlinedCard`, `FlowRow`\*, `FlowColumn`\*, `FlexBox`\*, `PullToRefreshBox`, `SwipeToDismissBox`, `VerticalDragHandle`, `HorizontalDivider`, `VerticalDivider`, `SelectionContainer`, `DisableSelection` |
| App bars | `TopAppBar`\*, `CenterAlignedTopAppBar`\*, `MediumTopAppBar`\*, `LargeTopAppBar`\*, `BottomAppBar`, `BottomAppBarActions` |
| Buttons | `Button`, `ElevatedButton`, `OutlinedButton`, `FilledTonalButton`, `TextButton`, `SegmentedButton`, `MultiChoiceSegmentedButton`, `SingleChoiceSegmentedButtonRow`, `MultiChoiceSegmentedButtonRow`, `IconButton`, `FilledIconButton`, `FilledIconToggleButton`, `FilledTonalIconButton`, `FilledTonalIconToggleButton`, `IconToggleButton`, `OutlinedIconButton`, `OutlinedIconToggleButton`, `FloatingActionButton`, `SmallFloatingActionButton`, `LargeFloatingActionButton`, `ExtendedFloatingActionButton`, `ExtendedFloatingActionButtonText` |
| Selection and input | `Checkbox`, `TriStateCheckbox`, `RadioButton`, `Switch`, `Slider`\*, `TextField`, `OutlinedTextField`, `SecureTextField`, `OutlinedSecureTextField`, `BasicTextField`, `ExposedDropdownMenuBox`\*, `ExposedDropdownMenu`\*, `AssistChip`, `ElevatedAssistChip`, `FilterChip`, `ElevatedFilterChip`, `SuggestionChip`, `ElevatedSuggestionChip`, `InputChip` |
| Search | `SearchBar`\*, `DockedSearchBar`\*, `SearchBarInputField`\*, `StatefulSearchBarInputField`\*, `StatefulSearchBar`\*, `SearchBarStateInputField`\*, `ExpandedDockedSearchBar`\*, `ExpandedFullScreenSearchBar`\* |
| Pickers | `DatePicker`, `DatePickerDialog`, `TimePicker`\*, `TimeInput`\*, `TimePickerDialog` |
| Navigation and drawers | `NavigationBar`, `NavigationBarItem`, `NavigationRail`, `NavigationRailItem`, `ShortNavigationBar`, `ShortNavigationBarItem`, `WideNavigationRail`, `WideNavigationRailItem`, `ModalWideNavigationRail`, `NavigationSuiteScaffold`, `NavigationSuiteScaffoldLayout`, `NavigationSuite`, `NavigationSuiteItem`, `NavigationDrawerItem`, `ModalNavigationDrawer`, `ModalDrawerSheet`, `DismissibleNavigationDrawer`, `DismissibleDrawerSheet`, `PermanentNavigationDrawer`, `PermanentDrawerSheet`, `Tab`, `TabContent`, `LeadingIconTab`, `PrimaryTabRow`, `SecondaryTabRow`, `PrimaryScrollableTabRow`, `SecondaryScrollableTabRow` |
| Overlays and status | `ModalBottomSheet`\*, `AlertDialog`, `BasicAlertDialog`\*, `DropdownMenu`, `DropdownMenuItem`, `TooltipBox`\*, `PlainTooltip`\*, `RichTooltip`\*, `Snackbar`, `SnackbarHost`, `Badge`, `BadgedBox`, `CircularProgressIndicator`, `LinearProgressIndicator`\* |
| Lists | `LazyColumn`, `LazyRow`, `ListItem` |
| Animation | `AnimatedVisibility`, `AnimatedContent`, `Crossfade`, `SharedTransitionLayout` |
| Media | `Icon`, `Image` |

`pycompose add group:artifact[:version]` wraps another Compose library from
Maven into the app's own catalog, through the same compiler; each of its
components is rendered once on the JVM before it is exposed. A component the
host lacks shows its declared fallback instead of failing.

`DatePicker`, `TimePicker` and `TimeInput` are controlled through their state's
own properties: `selected_date_millis`, `hour`, `minute`. Setting `hour` from
Python moves the analog dial's hand as well as the number.

`ExposedDropdownMenuBox` opens from the child wearing `menu_anchor`, usually a
field or a text: `Modifier.menu_anchor(ExposedDropdownMenuAnchorType("PrimaryNotEditable"))`,
with the anchor type from `pycompose.values`.

`SearchBar` and `DockedSearchBar` take the editable field through the
`inputField` slot; suggestions and results are ordinary children and compose in
`ColumnScope`. `SearchBarInputField` is the same native field without a
container, for layouts that place the field themselves.

`StatefulSearchBarInputField` selects the native `TextFieldState` overload with
explicit `expanded`/`on_expanded_change`. Supply `text`, `selection_start`,
`selection_end`, `revision`, `on_edit`, and `on_search`. The edit handler's
`TypedDict` has `text: str`, `selection_start: int`, `selection_end: int`, and
`revision: int`; store and echo all four together. Selection uses **UTF-16 code
units**, not Python string indices, and preserves reversed ranges. Native edits
advance the revision; old echoes cannot undo newer typing. A deliberate app edit
uses a greater revision. Keep the node id stable while editing; a new id starts
from the snapshot. Start revisions at zero; if the signed 64-bit maximum is
reached, further native edits are rejected with a diagnostic until a new node id
starts a fresh sequence. Acknowledgements do not generate another edit report or reset
unchanged IME composition. `on_search` receives `query: str`.

This overload adds `read_only`, `text_style`, `prefix`, `suffix`, `shape`, and
`colors`, retaining native defaults when absent. It is **partial coverage**:
input/output transformations, explicit horizontal scroll control, and
interaction observations remain gaps. Existing `SearchBarInputField`,
`SearchBar`, and `DockedSearchBar` APIs are unchanged.

`StatefulSearchBar` owns one search. Supply `text`, `selection_start`,
`selection_end`, `revision`, and `on_edit`; supply `expanded` and
`on_expanded_change` to drive and observe expansion, or omit `expanded` to leave
it to native focus and gestures. Its `input_field` slot holds a
`SearchBarStateInputField`; its `expanded_bar` slot holds
`ExpandedDockedSearchBar` or `ExpandedFullScreenSearchBar`, each with its own
`input_field` slot. Every surface reads the owner's native editing and expansion
state, so text, selection, and revision survive expanding, collapsing, or a
snapshot pull. A field or expanded surface outside a `StatefulSearchBar` is
diagnosed by the host instead of creating a second state.

`TooltipBox` anchors its `tooltip` slot to its ordinary children. Put
`PlainTooltip` or `RichTooltip` directly in that slot: they require its native
`TooltipScope`. Rich tooltips also accept `title` and `action` slots. Colors and
dimensions use Material 3 defaults unless supplied.

Omit `visible` for native long-press, hover and keyboard behavior. Changing it
requests a show or dismissal; `on_visibility_change` reports a boolean `visible`
payload, including native dismissal. Repeating a snapshot does not reopen a
dismissed tooltip. Set `is_persistent=True` for actionable content and
`has_action=True` for its native accessibility/keyboard behavior. Native tooltip
arbitration permits one active tooltip at a time.

`SwipeToDismissBox` takes ordinary children as the content row and a
`background_content` slot behind it. Supply `value` (`"settled"`,
`"startToEnd"`, or `"endToStart"`) and `on_value_change` to drive and observe
the settled anchor; omit `value` to leave it to gestures. The report payload is
one `value: str` field. The first snapshot seeds the anchor without a report;
native swipes report the anchor they settled on. Both directions and gestures
are enabled unless `enable_dismiss_from_start_to_end`,
`enable_dismiss_from_end_to_start`, or `gestures_enabled` say otherwise.

`ModalBottomSheet` retains `open`/`on_open_change` and also accepts `value`
(`"hidden"`, `"partiallyExpanded"`, `"expanded"`) with `on_value_change`.
An explicit `value` takes precedence over `open`; its report carries one
`value: str` field naming the actual settled anchor. Partial expansion requires
a native partial anchor; short sheets or `skip_partially_expanded=True` fall
back to expanded. Hidden sheets leave native composition after settling so they
cannot block the app. The boolean observer reports visibility changes, while
the anchor observer also reports partial/expanded changes. Initial display uses
the native opening animation and reports the reconciled anchor. If that opening
is dismissed before it commits, the observers report `hidden` and a failed
`open` request.

## CLI

| Command | What it does |
| --- | --- |
| `pycompose init <name> [--template blocks\|viewmodel] [--native]` | Scaffold a project, starting from blocks (the default) or a view model; `--native` keeps Android sources at the root |
| `pycompose run [--device <serial>] [--dev-client]` | Build, install, launch, and watch `.py` and `resources/` for hot reload; `--dev-client` skips the app's Gradle build |
| `pycompose dev-client [--rebuild]` | Build the prebuilt dev client once for this PyCompose version |
| `pycompose debug [--no-launch]` | One build-install-launch pass, no watcher |
| `pycompose check` | Find what a build or the store would refuse, without either |
| `pycompose render [<snapshot.json>…] [--out <dir>]` | Screenshot the app and dump its semantics on the JVM, with no device |
| `pycompose bench [--keys N] [--interval S]` | Type into the running debug app and report each stage of a pass: median, 95th percentile, worst |
| `pycompose build [apk\|aab] [--release]` | Package through the project's Gradle wrapper |
| `pycompose install [--release] [--launch]` | Install a built APK and verify the installed bytes match the artifact |
| `pycompose release [apk\|aab] [--install]` | Build a signed release artifact |
| `pycompose add <group:artifact[:version]>` | Wrap a Compose library from Maven into the app's catalog |
| `pycompose config show` / `set <key> <value>` | Read or rewrite `label`, `application_id`, `version_name`, `version_code` |
| `pycompose prebuild` / `explain <file>` | Generate the Android project and show what changed; name the settings behind a generated file |
| `pycompose migrate` | Move an app-owned Android project to a generated one |
| `pycompose setup` | Install the pinned JDK and Android SDK |
| `pycompose sync [--check]` | Sync named resources into the host; `--check` reports drift only |
| `pycompose doctor` | Report Android toolchain and schema compatibility |
| `pycompose validate <file>` | Validate IR JSON against the registry and wire schema |
| `pycompose stubs <path>` | Print optional module stubs from a project's declarations without importing app code |

Release signing reads `[signing]` from `pycompose.toml` and the passwords from
the `PYCOMPOSE_STORE_PASSWORD` and `PYCOMPOSE_KEY_PASSWORD` environment
variables.

## Measuring

A debug build logs one line per pass, under the `PyCompose.pass` logcat tag,
when the frame showing it is drawn. Each line has the time spent in each stage:
the queue, the Python pass (split into handler, view, validation and
serialization), the pull, the host's apply, and the frame. Focus a text field in
the running app and run `pycompose bench` to type into it and summarize:

```
40 passes for 40 keystrokes (ms)
stage           p50      p95      max
python          6.4      8.4     10.6
apply           1.9      2.6      3.8
frame          27.6     33.1     42.4
total          36.9     42.6     51.0
```

That is the notes example's editor on an arm64 emulator, warm; measure on the
phones you target, and run it more than once, since the first passes after an
install are much slower.

## Python libraries

Python libraries stay ordinary Python libraries. Declare them, and any Android
permission they need, in `pycompose.toml`:

```toml
[python]
requirements = ["httpx>=0.27,<0.29"]

[android]
permissions = ["android.permission.INTERNET"]
```

Builds install the requirements; permissions feed a generated manifest while
your native edits stay intact. A view model runs a blocking call off the loop
with `await to_thread("io", fn, *args)`, and computation with
`await to_thread("cpu", fn, *args)`; `examples/extensions` uses HTTPX and SQLite
that way. A blocks function needs neither: it already runs off the loop, so it
calls HTTPX or any other blocking library directly, as `examples/weather` does.

## Development

```bash
pip install -e ".[dev]"
pre-commit install
npm ci                                  # commit-message linting
make fmt && make precommit && make test
```

Commit messages follow Conventional Commits. A new package or boundary comes
with its contract in the same change.

The catalog lock, `schema/catalog.lock.json`, is generated and must reproduce
from the pinned Compose libraries plus the review decisions in
`schema/policy/`:

```bash
cd android && ./gradlew dumpComposeApi dumpComposeDefaults && cd ..
python -m pycompose.compiler generate   # rewrite the lock; --check verifies it
python tools/schema/gen.py              # regenerate code from it; --check verifies it
```

The compiler writes a report of what it derived and what it refused, with the
reason, to `android/build/compose-api/composegen-report.md`. Generated Python
components, Kotlin models and adapters, validators and the wire schema are
committed and never hand-edited; `make codegen-check` runs every check.

## License

MIT. See [LICENSE](LICENSE).
