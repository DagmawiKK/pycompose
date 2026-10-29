"""The pieces one adapter is assembled from."""

from __future__ import annotations


class Fragments:
    """The pieces one adapter is assembled from.

    A list of strings was enough until decoded props arrived, which needed three
    positions -- locals before the call, arguments inside it, and a trailing
    content lambda after it -- and a single growing list pushed `render` past
    the branch limit. Naming the three keeps each obvious.
    """

    def __init__(self) -> None:
        """Start empty."""
        self.locals: list[str] = []
        self.arguments: list[str] = []
        self.trailing: list[str] = []
        self.trailing_parameter: str | None = None
        self.gates: list[str] = []

    def add(self, fragment: tuple[str, str] | None) -> bool:
        """Append one prop's rendering.

        Args:
            fragment: The local/argument pair, or None to refuse.

        Returns:
            False when the prop cannot be rendered and the adapter is abandoned.
        """
        if fragment is None:
            return False
        local, argument = fragment
        if local:
            self.locals.append(local)
        if argument:
            self.arguments.append(argument)
        return True

    def trailing_lambda(self, body: str, parameter: str | None = None) -> None:
        """Record a content lambda that follows the call.

        Args:
            body: The lambda body, already indented.
            parameter: Lambda parameter name, for a slot that consumes a scope.
        """
        if body:
            self.trailing.append(body)
            self.trailing_parameter = parameter or self.trailing_parameter
