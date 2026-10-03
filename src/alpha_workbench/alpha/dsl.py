"""A deliberately tiny expression language for paper-research factors.

Parsing is explicit; expressions are never passed to ``eval`` or compiled as
Python.  This keeps model output untrusted and makes the generated formula
portable to the backtester later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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
        return _canonical_number(str(arg))
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


def _canonical_number(value: str) -> str:
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise DSLValidationError("invalid numeric literal") from error
    if not number.is_finite():
        raise DSLValidationError("numeric literals must be finite")
    normalized = format(number.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized


def canonicalize_expression(text: str, feature_names: set[str] | list[str]) -> str:
    """Return the stable DSL identity used for dedupe and strategy hashing."""
    return _canonical_render(parse_expression(text, feature_names))


def _canonical_render(node: Expression) -> str:
    if not node.args:
        try:
            return _canonical_number(node.name)
        except DSLValidationError:
            return node.name
    args = [
        _canonical_render(arg) if isinstance(arg, Expression) else str(arg)
        for arg in node.args
    ]
    if node.name in {"Add", "Mul"}:
        args.sort()
    return f"{node.name}({','.join(args)})"


def validate_typed_expression(
    expression: Expression,
    *,
    supported_axes: dict[str, tuple[str, ...]],
    frequency: str,
) -> None:
    """Validate operator axes and cadence-relative lookbacks deterministically.

    Lookback integers are observations at the strategy cadence (for example,
    ``Delay(x, 5)`` means five weekly rows for a weekly strategy).
    """
    del frequency  # cadence is retained by the signal; windows are observation counts.
    cross_section_ops = {"Rank", "ZScore"}
    time_series_ops = {"Delay", "Delta", "Mean", "StdDev", "Correlation"}

    def walk(node: Expression) -> set[str]:
        used = {node.name} if node.name in supported_axes else set()
        for arg in node.args:
            if isinstance(arg, Expression):
                used.update(walk(arg))
        if node.name in cross_section_ops | time_series_ops:
            axis = "cross_section" if node.name in cross_section_ops else "time_series"
            incompatible = sorted(name for name in used if axis not in supported_axes[name])
            if incompatible:
                raise DSLValidationError(
                    f"{node.name} requires {axis}-compatible features: {', '.join(incompatible)}"
                )
        period_index = 2 if node.name == "Correlation" else 1
        if node.name in {"Delay", "Delta", "Mean", "StdDev", "Correlation"}:
            period_node = node.args[period_index]
            try:
                if isinstance(period_node, Expression):
                    period_raw = float(period_node.name) if not period_node.args else float("nan")
                else:
                    period_raw = float(period_node)
            except (ValueError, TypeError):
                period_raw = float("nan")
            if not period_raw.is_integer() or not 1 <= period_raw <= 252:
                raise DSLValidationError("lookback must be an integer between 1 and 252")
        return used

    walk(expression)
