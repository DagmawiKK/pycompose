"""Terminal rendering for the CLI, layered on rich.

The CLI keeps two promises no matter how pretty it gets:

* text a script may read -- artifact paths, changed resource names, doctor
  lines -- is printed whole and unstyled, so a pipe or a log file sees the
  same characters a terminal shows;
* chrome -- steps, spinners, tables, panels -- exists only for a person, and
  a piped stdout loses the styling by itself.

Incoming text never passes through rich markup: values from a project file or
a child process become ``Text`` objects, so a bracket in a label or a Gradle
line is printed instead of interpreted.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from rich import box
from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

console = Console(highlight=False)
error_console = Console(stderr=True, highlight=False)


def line(text: str = "") -> None:
    """Print machine-relevant text as one whole, unstyled line."""
    console.print(text, soft_wrap=True, markup=False, highlight=False)


def echo(text: str) -> None:
    """Print one line of a child process's stdout, dimmed on a terminal."""
    console.print(text, soft_wrap=True, markup=False, highlight=False, style="dim")


def echo_error(text: str) -> None:
    """Print one line of a child process's stderr, dimmed on a terminal."""
    error_console.print(
        text, soft_wrap=True, markup=False, highlight=False, style="dim"
    )


def step(text: str) -> None:
    """Announce a phase the CLI is entering."""
    console.print(text, soft_wrap=True, markup=False, highlight=False, style="bold")


def ok(text: str) -> None:
    """Confirm an outcome."""
    console.print(Text.assemble(("✓ ", "green"), text), soft_wrap=True, highlight=False)


def notice(text: str) -> None:
    """Print something worth keeping in view."""
    console.print(Text.assemble(("• ", "cyan"), text), soft_wrap=True, highlight=False)


def warn(text: str) -> None:
    """Warn on stderr without failing the command."""
    error_console.print(
        Text.assemble(("warning: ", "yellow"), text), soft_wrap=True, highlight=False
    )


def error(command: str, message: str) -> None:
    """Report a failed command on stderr, without a traceback."""
    error_console.print(
        Text.assemble((f"pycompose {command}: ", "red bold"), message),
        soft_wrap=True,
        highlight=False,
    )


def check_line(passed: bool, name: str, detail: str) -> None:
    """Print one doctor line; the OK/FAIL prefix stays whole for scripts."""
    mark = Text("OK", style="green") if passed else Text("FAIL", style="red")
    console.print(
        Text.assemble(mark, f" {name}: {detail}"), soft_wrap=True, highlight=False
    )


def plain(text: str) -> Text:
    """Wrap incoming text so it renders literally."""
    return Text(text)


def table(*headers: str) -> Table:
    """Build a borderless table with the CLI's shared header style."""
    built = Table(box=box.SIMPLE, header_style="bold", pad_edge=False, show_edge=False)
    for header in headers:
        built.add_column(header)
    return built


def render(renderable: RenderableType) -> None:
    """Print a rich renderable (a table or a panel) on the CLI console."""
    console.print(renderable)


def panel(title: str, body: str) -> None:
    """Print a bordered summary box."""
    console.print(Panel(plain(body), title=title, border_style="cyan", expand=False))


@contextmanager
def working(text: str) -> Iterator[None]:
    """Show a spinner while a short step runs; print the text when piped."""
    if console.is_terminal:
        with console.status(text, spinner="dots"):
            yield
    else:
        console.print(text, soft_wrap=True, markup=False, highlight=False)
        yield


def interactive() -> bool:
    """Report whether the process can prompt a person."""
    return console.is_terminal and sys.stdin.isatty()


def ask(
    text: str, *, default: str | None = None, choices: Sequence[str] | None = None
) -> str:
    """Prompt for a value; only called when :func:`interactive` is true."""
    return str(
        Prompt.ask(
            text,
            default=default,
            choices=list(choices) if choices else None,
            console=console,
        )
    )


def confirm(text: str, *, default: bool = False) -> bool:
    """Ask a yes/no question; only called when :func:`interactive` is true."""
    return bool(Confirm.ask(text, default=default, console=console))
