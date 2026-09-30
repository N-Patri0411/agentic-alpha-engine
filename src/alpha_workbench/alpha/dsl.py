"""A deliberately tiny expression language for paper-research factors.

Parsing is explicit; expressions are never passed to ``eval`` or compiled as
Python.  This keeps model output untrusted and makes the generated formula
portable to the backtester later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar


class DSLValidationError(ValueError):
    """Raised when a factor expression is outside the approved DSL."""


@dataclass(frozen=True)
class Expression:
    name: str
    args: tuple[Expression | float | str, ...] = ()

    def render(self) -> str:
        if not self.args:
            return self.name
        return f"{self.name}({','.join(_render_arg(a) for a in self.args)})"

    def nodes(self) -> int:
        return 1 + sum(a.nodes() if isinstance(a, Expression) else 0 for a in self.args)


def _render_arg(arg: Expression | float | str) -> str:
    if isinstance(arg, Expression):
        return arg.render()
    if isinstance(arg, float):
        return f"{arg:g}"
    return arg


class _Parser:
    FUNCTIONS: ClassVar[dict[str, tuple[int, int]]] = {
        "Rank": (1, 1),
        "ZScore": (1, 1),
        "Delay": (2, 2),
        "Delta": (2, 2),
        "Mean": (2, 2),
        "StdDev": (2, 2),
        "Correlation": (3, 3),
        "Add": (2, 2),
        "Sub": (2, 2),
        "Mul": (2, 2),
        "Div": (2, 2),
        "Neg": (1, 1),
        "Clip": (3, 3),
    }

    def __init__(self, text: str, features: set[str], max_nodes: int) -> None:
        if len(text) > 300 or not text.strip():
            raise DSLValidationError("expression is empty or exceeds 300 characters")
        self.tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.]*|-?(?:\d+(?:\.\d*)?|\.\d+)|[(),]", text)
        compact = re.sub(r"\s+", "", text)
        if "".join(self.tokens) != compact:
            raise DSLValidationError("expression contains unsupported syntax")
        self.i = 0
        self.features = features
        self.max_nodes = max_nodes

    def parse(self) -> Expression:
        value = self.expr()
        if self.i != len(self.tokens):
            raise DSLValidationError("unexpected trailing tokens")
        if value.nodes() > self.max_nodes:
            raise DSLValidationError("expression exceeds node limit")
        return value

    def expr(self) -> Expression:
        if self.i >= len(self.tokens):
            raise DSLValidationError("expected expression")
        token = self.tokens[self.i]
        self.i += 1
        if re.fullmatch(r"-?(?:\d+(?:\.\d*)?|\.\d+)", token):
            return Expression(token)
        if token in self.features:
            return Expression(token)
        if token not in self.FUNCTIONS:
            raise DSLValidationError(f"unknown identifier {token!r}")
        if self.i >= len(self.tokens) or self.tokens[self.i] != "(":
            raise DSLValidationError(f"{token} must be called")
        self.i += 1
        args: list[Expression | float | str] = []
        if self.i < len(self.tokens) and self.tokens[self.i] != ")":
            while True:
                arg = self.expr()
                args.append(arg)
                if self.i >= len(self.tokens) or self.tokens[self.i] != ",":
                    break
                self.i += 1
        if self.i >= len(self.tokens) or self.tokens[self.i] != ")":
            raise DSLValidationError("missing closing parenthesis")
        self.i += 1
        lo, hi = self.FUNCTIONS[token]
        if not lo <= len(args) <= hi:
            raise DSLValidationError(f"{token} expects {lo} to {hi} arguments")
        return Expression(token, tuple(args))


def parse_expression(
    text: str, feature_names: set[str] | list[str], *, max_nodes: int = 25
) -> Expression:
    """Parse and validate one expression against the supplied feature names."""
    return _Parser(text, set(feature_names), max_nodes).parse()
