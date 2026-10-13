"""Generate optional Python stubs by parsing declarations, never importing apps."""

from __future__ import annotations

import ast
from pathlib import Path

from pycompose.cli.project import ProjectError


def _name(value: ast.expr) -> str:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return f"{_name(value.value)}.{value.attr}"
    return ""


class _Declarations:
    def __init__(self, aliases: set[str]) -> None:
        self.aliases = aliases

    def function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.stmt:
        is_composable = any(
            _name(decorator) in self.aliases for decorator in node.decorator_list
        )
        if is_composable:
            if (
                isinstance(node, ast.AsyncFunctionDef)
                or node.args.posonlyargs
                or node.args.vararg
            ):
                raise ProjectError(
                    "composable signatures must be synchronous and keyword-callable",
                    name=node.name,
                )
            arguments = [*node.args.args, *node.args.kwonlyargs]
            if any(argument.arg == "id" for argument in arguments):
                raise ProjectError("composable reserves id", name=node.name)
            defaults: list[ast.expr | None] = [None] * (
                len(node.args.args) - len(node.args.defaults)
            )
            defaults.extend(node.args.defaults)
            node.args.kwonlyargs = [
                ast.arg(arg="id", annotation=ast.Name(id="str")),
                *arguments,
            ]
            node.args.kw_defaults = [None, *defaults, *node.args.kw_defaults]
            node.args.args = []
            node.args.defaults = []
            node.returns = ast.Name(id="_PyComposeNode")
            node.decorator_list = []
        for argument in [
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ]:
            if argument.annotation is None:
                argument.annotation = ast.Name(id="_StubAny")
        node.returns = node.returns or ast.Name(id="_StubAny")
        node.body = [ast.Expr(value=ast.Constant(value=Ellipsis))]
        return node

    def declarations(self, statements: list[ast.stmt]) -> list[ast.stmt]:
        result: list[ast.stmt] = []
        for node in statements:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                result.append(self.function(node))
            elif isinstance(node, ast.ClassDef):
                node.body = self.declarations(node.body) or [
                    ast.Expr(value=ast.Constant(value=Ellipsis))
                ]
                result.append(node)
            elif isinstance(node, ast.Import | ast.ImportFrom | ast.TypeAlias):
                result.append(node)
            elif isinstance(node, ast.AnnAssign):
                node.value = ast.Constant(value=Ellipsis)
                result.append(node)
            elif isinstance(node, ast.Assign):
                result.extend(
                    ast.AnnAssign(
                        target=target,
                        annotation=ast.Name(id="_StubAny"),
                        value=ast.Constant(value=Ellipsis),
                        simple=1,
                    )
                    for target in node.targets
                    if isinstance(target, ast.Name)
                )
            elif isinstance(node, ast.If) and _name(node.test) in {
                "TYPE_CHECKING",
                "typing.TYPE_CHECKING",
            }:
                result.extend(self.declarations(node.body))
        return result


def generate_stubs(path: Path) -> str:
    """Render optional module stubs without executing or overwriting user code.

    Typed composable props retain their annotations. The injected instance id
    is keyword-only and the return type is Node, reflecting deferred execution.
    Unannotated declarations use Any rather than inventing an inferred type.

    Args:
        path: Python module whose declarations should be represented.

    Returns:
        Stub source ready to redirect to a sibling .pyi file.

    Raises:
        ProjectError: If the source or a composable signature is invalid.
    """
    try:
        source = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeError) as exc:
        raise ProjectError(
            "cannot parse stub source", path=path, reason=str(exc)
        ) from exc
    aliases: set[str] = set()
    for node in source.body:
        if isinstance(node, ast.ImportFrom) and node.module in {
            "pycompose",
            "pycompose.composition",
        }:
            aliases.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "composable"
            )
        elif isinstance(node, ast.Import):
            aliases.update(
                f"{alias.asname or alias.name}.composable"
                for alias in node.names
                if alias.name in {"pycompose", "pycompose.composition"}
            )
    declarations = _Declarations(aliases).declarations(source.body)
    futures = [
        node
        for node in declarations
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
    ]
    others = [node for node in declarations if node not in futures]
    imports = ast.parse(
        "from typing import Any as _StubAny\n"
        "from pycompose.core import Node as _PyComposeNode\n"
    ).body
    module = ast.fix_missing_locations(
        ast.Module(body=[*futures, *imports, *others], type_ignores=[])
    )
    return (
        "# GENERATED by pycompose stubs; regenerate after changing signatures.\n"
        + ast.unparse(module)
        + "\n"
    )
