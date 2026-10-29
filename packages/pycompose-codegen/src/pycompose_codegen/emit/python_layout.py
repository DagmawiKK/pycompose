"""Layout of generated component lines: each kept inside ruff's 88 columns.

The generated module is committed and checked by ``ruff format``, so a line a
long component name would overflow is emitted already wrapped, as the
formatter would wrap it.
"""

from __future__ import annotations

import textwrap

COLUMNS = 88


def class_docstring(native: str) -> list[str]:
    """Render the generated class docstring, wrapped when the summary is long.

    Args:
        native: The native callable the schema entry binds.

    Returns:
        The docstring's source lines.
    """
    summary = f"Native {native}; props and defaults follow the component manifest."
    if len(f'    """{summary}"""') <= COLUMNS:
        return [f'    """{summary}"""']
    return [
        f'    """Native {native};',
        '    props and defaults follow the component manifest."""',
    ]


def class_header(class_name: str, base: str, name: str) -> tuple[str, str]:
    """A class header and its constructor's summary line.

    Args:
        class_name: The generated class.
        base: The class it subclasses.
        name: The component, which the summary names.

    Returns:
        The header, and the summary without its quotes.
    """
    header = f"class {class_name}({base}):"
    if len(header) > COLUMNS:
        header = f"class {class_name}(\n    {base}\n):"
    summary = f"Construct a registered {name}."
    if len(f'        """{summary}') > COLUMNS:
        summary = f"Construct {name}."
    return header, summary


def overloads_line(name: str, overloads: list[str]) -> str:
    """The assignment listing a primary's overloads.

    Args:
        name: The primary component.
        overloads: Its overload classes.

    Returns:
        The statement, one overload per line when it does not fit on one.
    """
    listed = ", ".join(overloads) + ("," if len(overloads) == 1 else "")
    line = f"{name}.overloads = ({listed})"
    if len(line) <= COLUMNS:
        return line
    return f"{name}.overloads = (\n" + "".join(f"    {o},\n" for o in overloads) + ")"


def docstring_arg(field: str, description: str) -> list[str]:
    """Render one constructor Args entry inside the 88-column budget.

    A long prop name plus its fixed note can cross the formatter's line
    limit, and a generated file must survive the same lint as a hand-written
    one, so the entry wraps at a word boundary under the Args indent.

    Args:
        field: The constructor parameter's name.
        description: Its one-line note.

    Returns:
        The entry's lines, continuations indented under the first.
    """
    wrapped = textwrap.wrap(f"{field}: {description}", width=72) or [f"{field}:"]
    return [f"            {wrapped[0]}"] + [
        f"                {rest}" for rest in wrapped[1:]
    ]
