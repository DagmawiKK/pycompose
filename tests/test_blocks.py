"""Blocks apps: events run functions off the loop and write their outputs."""

from __future__ import annotations

import json
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import pycompose.blocks as pc
from pycompose.errors import StateError
from pycompose.testing.driver import AppDriver

GREET = """
import threading
import pycompose.blocks as pc

GATE = threading.Event()
GATE.set()

def greet(name, times):
    GATE.wait(5)
    if name == "boom":
        raise ValueError("no booms")
    return f"Hello, {name}" * times

def both(name):
    return name.upper(), len(name)

def short(name):
    return (name,)

with pc.Blocks() as app:
    name = pc.Textbox(label="Name")
    times = pc.Number(1, label="Times", precision=0)
    out = pc.Textbox(label="Greeting", interactive=False)
    loud = pc.Textbox(label="Loud", interactive=False)
    size = pc.Number(label="Size", interactive=False)
    pc.Button("Greet").click(greet, inputs=[name, times], outputs=out)
    pc.Button("Both").click(both, inputs=name, outputs=[loud, size])
    pc.Button("Short").click(short, inputs=name, outputs=[loud, size])
    name.change(lambda text: text[::-1], inputs=name, outputs=loud)
"""


def project(root: Path, source: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pycompose.toml").write_text(
        '[app]\nname = "Demo"\napplication_id = "com.example.demo"\n'
        '[python]\nentrypoint = "main:app"\nsource_dir = "app"\n'
    )
    (root / "app").mkdir(exist_ok=True)
    (root / "app/main.py").write_text(textwrap.dedent(source))
    return root


@pytest.fixture
def greet(tmp_path: Path) -> Iterator[AppDriver]:
    with AppDriver(project(tmp_path / "greet", GREET)) as driver:
        yield driver


def value(app: AppDriver, label: str) -> Any:
    return app.find(label=label)["props"]["value"]


def toasts(app: AppDriver) -> list[str]:
    return [e["payload"]["message"] for e in app.effects if e["kind"] == "toast"]


def busy(app: AppDriver) -> bool:
    return any(
        n["type"] == "AnimatedVisibility" and n["props"]["visible"] for n in app.nodes()
    )


def test_a_click_runs_the_function_with_its_inputs_and_writes_its_output(
    greet: AppDriver,
) -> None:
    greet.edit("Ada", label="Name")
    greet.edit("2", label="Times")
    greet.click(text="Greet")
    greet.settle()
    assert value(greet, "Greeting") == "Hello, AdaHello, Ada"
    assert greet.failures == []


def test_an_output_shows_progress_only_while_its_function_runs(
    greet: AppDriver,
) -> None:
    gate = sys.modules["main"].GATE
    gate.clear()
    greet.click(text="Greet")
    assert busy(greet)
    gate.set()
    greet.settle()
    assert not busy(greet)
    assert value(greet, "Greeting") == "Hello, "


def test_a_change_runs_its_function_on_every_edit(greet: AppDriver) -> None:
    greet.edit("abc", label="Name")
    greet.settle()
    assert value(greet, "Loud") == "cba"


def test_several_outputs_take_one_value_each(greet: AppDriver) -> None:
    greet.edit("ada", label="Name")
    greet.click(text="Both")
    greet.settle()
    assert (value(greet, "Loud"), value(greet, "Size")) == ("ADA", "3")


def test_a_failure_becomes_a_toast_and_leaves_the_outputs(greet: AppDriver) -> None:
    greet.edit("boom", label="Name")
    greet.click(text="Greet")
    greet.settle()
    assert toasts(greet) == ["no booms"]
    assert value(greet, "Greeting") == ""
    assert not busy(greet)


def test_too_few_results_for_the_outputs_is_a_toast(greet: AppDriver) -> None:
    greet.click(text="Short")
    greet.settle()
    assert toasts(greet) == ["expected 2 results, one per output"]


def test_an_unreadable_number_is_a_toast_and_runs_nothing(greet: AppDriver) -> None:
    greet.edit("two", label="Times")
    greet.click(text="Greet")
    assert toasts(greet) == ["Times: 'two' is not a number"]
    assert not busy(greet)


def test_a_newer_run_supersedes_one_still_running(greet: AppDriver) -> None:
    gate = sys.modules["main"].GATE
    gate.clear()
    greet.edit("first", label="Name")
    greet.click(text="Greet")
    greet.edit("second", label="Name")
    greet.click(text="Greet")
    gate.set()
    greet.settle()
    assert value(greet, "Greeting") == "Hello, second"


def test_values_survive_process_death_and_progress_does_not(tmp_path: Path) -> None:
    root = project(tmp_path / "greet", GREET)
    with AppDriver(root) as first:
        first.edit("Ada", label="Name")
        sys.modules["main"].GATE.clear()
        first.click(text="Greet")
        saved = json.dumps(first.snapshot()["metadata"]["data"])
        sys.modules["main"].GATE.set()
        first.settle()
    with AppDriver(root, restore=saved) as second:
        assert value(second, "Name") == "Ada"
        assert not busy(second)


CHOICES = """
import pycompose.blocks as pc

with pc.Blocks() as app:
    with pc.Tabs():
        with pc.Tab("Pick"):
            size = pc.Dropdown(["S", "M", "L"], "M", label="Size")
            color = pc.Radio(["red", "blue"], label="Color")
            ok = pc.Checkbox(label="Agree")
            level = pc.Slider(0, 10, 5, step=1, label="Level")
        with pc.Tab("More"):
            with pc.Accordion("Details"):
                pc.Markdown("Hidden until opened")
    summary = pc.Markdown()
    pc.Button("Sum").click(
        lambda *v: " ".join(map(str, v)), [size, color, ok, level], summary
    )
"""


def test_choices_flags_and_sliders_report_through_their_native_controls(
    tmp_path: Path,
) -> None:
    with AppDriver(project(tmp_path / "choices", CHOICES)) as app:
        menu = app.find(type="ExposedDropdownMenuBox")
        app.act("onExpandedChange", menu, expanded=True)
        assert app.find(type="ExposedDropdownMenuBox")["props"]["expanded"]
        app.click(text="L")
        assert not app.find(type="ExposedDropdownMenuBox")["props"]["expanded"]
        app.click(text="blue")  # the row's radio button
        app.act("onCheckedChange", app.find(type="Checkbox"), value=True)
        app.act("onValueChangeFinished", app.find(type="Slider"), value=7.0)
        app.click(text="Sum")
        app.settle()
        assert "L blue True 7.0" in app.texts()


def section_open(app: AppDriver) -> bool:
    (section,) = (
        n
        for n in app.nodes()
        if n["type"] == "AnimatedVisibility" and "Hidden until opened" in json.dumps(n)
    )
    return bool(section["props"]["visible"])


def test_tabs_show_one_page_and_an_accordion_opens(tmp_path: Path) -> None:
    with AppDriver(project(tmp_path / "choices", CHOICES)) as app:
        assert "Size" in app.texts()
        app.click(text="More")
        assert "Size" not in app.texts()
        assert not section_open(app)
        app.click(text="Details")
        assert section_open(app)


def test_an_interface_stacks_inputs_a_button_and_outputs(tmp_path: Path) -> None:
    source = """
    import pycompose.blocks as pc

    app = pc.Interface(
        lambda a, b: a + b,
        [pc.Number(label="A"), pc.Number(label="B")],
        pc.Number(label="Sum"),
    )
    """
    with AppDriver(project(tmp_path / "sum", source)) as app:
        app.edit("2", label="A")
        app.edit("3.5", label="B")
        app.click(text="Submit")
        app.settle()
        assert value(app, "Sum") == "5.5"


def test_the_same_code_names_the_same_nodes(tmp_path: Path) -> None:
    root = project(tmp_path / "greet", GREET)
    with AppDriver(root) as first:
        before = first.snapshot()["root"]
    with AppDriver(root) as second:
        assert second.snapshot()["root"] == before


def test_a_choice_must_offer_its_value() -> None:
    with pytest.raises(StateError, match="one of them"):
        pc.Dropdown(["a"], "b")
    with pytest.raises(StateError, match="minimum < maximum"):
        pc.Slider(5, 1)


WEATHER = Path(__file__).resolve().parents[1] / "examples/weather"


def test_the_weather_example_fills_both_tabs_from_its_two_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    replies = {
        "search": {
            "results": [
                {"name": "Lima", "country": "Peru", "latitude": 1, "longitude": 2}
            ]
        },
        "forecast": {
            "current": {"temperature_2m": 19.5, "wind_speed_10m": 9, "weather_code": 3},
            "daily": {
                "time": ["2026-10-29", "2026-10-30"],
                "temperature_2m_min": [15, 14],
                "temperature_2m_max": [21, 20],
                "precipitation_probability_max": [10, 80],
                "weather_code": [3, 61],
            },
        },
    }

    def get(url: str, **_options: Any) -> httpx.Response:
        return httpx.Response(200, json=replies[url.rsplit("/", 1)[-1]])

    monkeypatch.setattr(httpx, "get", get)
    with AppDriver(WEATHER) as app:
        app.edit("Lima", label="City")
        app.act("onCheckedChange", app.find(type="Checkbox"), value=True)
        app.click(text="Get forecast")
        app.settle()
        assert "Lima, Peru\n19.5°C, overcast, wind 9 km/h" in app.texts()
        app.click(text="Days ahead")
        assert "2026-10-30: 14 to 20°C, rain, 80% rain" in app.texts()


def test_the_weather_example_asks_for_a_city_first() -> None:
    with AppDriver(WEATHER) as app:
        app.click(text="Get forecast")
        app.settle()
        assert toasts(app) == ["Type a city first"]


STREAM = """
import asyncio
import threading
import pycompose.blocks as pc

STEP = threading.Semaphore(0)
CLOSED = []

def words(text):
    try:
        shown = ""
        for word in text.split():
            STEP.acquire(timeout=5)
            shown = f"{shown} {word}".strip()
            yield shown
    finally:
        CLOSED.append(text)

async def letters(text):
    for i in range(1, len(text) + 1):
        await asyncio.sleep(0)
        yield text[:i]

with pc.Blocks() as app:
    text = pc.Textbox(label="Text")
    out = pc.Textbox(label="Out", interactive=False)
    pc.Button("Words").click(words, text, out)
    pc.Button("Letters").click(letters, text, out)
"""


@pytest.fixture
def stream(tmp_path: Path) -> Iterator[AppDriver]:
    with AppDriver(project(tmp_path / "stream", STREAM)) as driver:
        yield driver


def test_a_generator_shows_each_value_as_it_is_yielded(stream: AppDriver) -> None:
    step = sys.modules["main"].STEP
    stream.edit("one two three", label="Text")
    stream.click(text="Words")
    step.release()
    stream.wait_until(lambda: value(stream, "Out") == "one")
    assert busy(stream)
    step.release(2)
    stream.settle()
    assert value(stream, "Out") == "one two three"
    assert not busy(stream)


def test_an_async_generator_streams_on_the_loop(stream: AppDriver) -> None:
    stream.edit("abc", label="Text")
    stream.click(text="Letters")
    stream.settle()
    assert value(stream, "Out") == "abc"


def test_a_superseded_stream_stops_and_closes(stream: AppDriver) -> None:
    main = sys.modules["main"]
    stream.edit("old words here", label="Text")
    stream.click(text="Words")
    main.STEP.release()
    stream.wait_until(lambda: value(stream, "Out") == "old")
    stream.edit("new", label="Text")
    stream.click(text="Words")
    main.STEP.release(2)
    stream.settle()
    assert value(stream, "Out") == "new"
    # The stopped run closes as soon as its thread next looks; either may be first.
    assert sorted(main.CLOSED) == ["new", "old words here"]


CHAT = """
import pycompose.blocks as pc

SEEN = []

def reply(message, history):
    SEEN.append((message, [m["content"] for m in history]))
    text = ""
    for word in f"You said {message}".split():
        text = f"{text} {word}".strip()
        yield text

app = pc.ChatInterface(reply)
"""


def messages(app: AppDriver) -> list[str]:
    """The texts of the chat's bubbles, oldest first."""
    return [
        n["props"]["text"]
        for n in app.nodes()
        if n["type"] == "Text" and "slot" not in n and n["props"]["text"] != "…"
    ]


def test_a_chat_shows_the_message_then_streams_the_reply(tmp_path: Path) -> None:
    with AppDriver(project(tmp_path / "chat", CHAT)) as app:
        field = app.find(type="OutlinedTextField")
        app.act("onValueChange", field, value="hi")
        app.click(text="Send")
        app.settle()
        assert messages(app)[:2] == ["hi", "You said hi"]
        assert app.find(type="OutlinedTextField")["props"]["value"] == ""
        app.act("onValueChange", app.find(type="OutlinedTextField"), value="again")
        app.click(text="Send")
        app.settle()
        assert sys.modules["main"].SEEN[-1] == ("again", ["hi", "You said hi"])


def test_an_empty_message_sends_nothing(tmp_path: Path) -> None:
    with AppDriver(project(tmp_path / "chat", CHAT)) as app:
        app.click(text="Send")
        app.settle()
        assert sys.modules["main"].SEEN == []


def test_a_chat_message_needs_a_known_role() -> None:
    with pytest.raises(ValueError, match="role"):
        pc.Chatbot([{"role": "robot", "content": "beep"}])


CHAT_EXAMPLE = Path(__file__).resolve().parents[1] / "examples/chat"


def test_the_chat_example_streams_a_server_sent_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    sent: list[dict[str, Any]] = []

    def server(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        chunks = [
            f'data: {{"choices":[{{"delta":{{"content":"{word}"}}}}]}}\n\n'
            for word in ("Hello", " there")
        ]
        return httpx.Response(200, content="".join(chunks) + "data: [DONE]\n\n")

    client = httpx.Client(transport=httpx.MockTransport(server))
    monkeypatch.setattr(httpx, "stream", client.stream)
    with AppDriver(CHAT_EXAMPLE) as app:
        app.act("onValueChange", app.find(type="OutlinedTextField"), value="hi")
        app.click(text="Send")
        app.settle()
        assert messages(app)[:2] == ["hi", "Hello there"]
    assert sent[0]["stream"] is True
    assert sent[0]["messages"] == [{"role": "user", "content": "hi"}]
